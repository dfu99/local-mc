// local-mc front-end. Vanilla ES modules, no dependencies, no CDNs.
// State lives in memory; the source of truth is the server (SQLite).

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  projects: [],
  activeProject: null,        // project name
  activeSession: null,        // {id, project, ...}
  ws: null,
  staged: [],                 // [{filename, path, mime, size}]
  streamingMessageId: null,
};

// ── API ────────────────────────────────────────────────────────────────

const api = {
  async listProjects() {
    const r = await fetch("/api/projects");
    if (!r.ok) throw new Error(`projects: ${r.status}`);
    return r.json();
  },
  async addProject(p) {
    const r = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async listSessions(name) {
    const r = await fetch(`/api/projects/${encodeURIComponent(name)}/sessions`);
    if (!r.ok) throw new Error(`sessions: ${r.status}`);
    return r.json();
  },
  async createSession(name) {
    const r = await fetch(
      `/api/projects/${encodeURIComponent(name)}/sessions`,
      { method: "POST" }
    );
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async messages(sid) {
    const r = await fetch(`/api/sessions/${sid}/messages`);
    if (!r.ok) throw new Error(`messages: ${r.status}`);
    return r.json();
  },
  async upload(sid, file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/sessions/${sid}/upload`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};

// ── Project sidebar ────────────────────────────────────────────────────

async function refreshProjects() {
  state.projects = await api.listProjects();
  const list = $("#project-list");
  list.innerHTML = "";
  for (const p of state.projects) {
    const btn = document.createElement("button");
    btn.className = "project-item";
    if (!p.exists) btn.classList.add("missing");
    if (p.name === state.activeProject) btn.classList.add("active");
    btn.dataset.name = p.name;
    btn.innerHTML = `
      <span class="project-name"></span>
      <span class="project-tags"></span>
    `;
    btn.querySelector(".project-name").textContent = p.name;
    btn.querySelector(".project-tags").textContent =
      (p.tags || []).join(" · ") || p.path;
    btn.addEventListener("click", () => selectProject(p.name));
    list.appendChild(btn);
  }
}

async function selectProject(name) {
  state.activeProject = name;
  await refreshProjects();
  const proj = state.projects.find((p) => p.name === name);
  if (!proj) return;
  $("#project-title").innerHTML = `
    <span class="project-name"></span>
    <span class="project-meta"></span>
  `;
  $("#project-title .project-name").textContent = proj.name;
  $("#project-title .project-meta").textContent = proj.path;

  $("#new-session").hidden = false;
  $("#session-picker").hidden = false;

  const sessions = await api.listSessions(name);
  const picker = $("#session-picker");
  picker.innerHTML = "";
  if (sessions.length === 0) {
    const sess = await api.createSession(name);
    sessions.push(sess);
  }
  for (const s of sessions) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = formatTime(s.last_active_at) + " · " + s.id.slice(0, 6);
    picker.appendChild(opt);
  }
  picker.value = sessions[0].id;
  await openSession(sessions[0]);
}

async function openSession(sess) {
  state.activeSession = sess;
  state.staged = [];
  renderTray();
  $("#input").disabled = false;
  $("#send").disabled = false;
  closeSocket();

  const msgs = await api.messages(sess.id);
  const container = $("#messages");
  container.innerHTML = "";
  for (const m of msgs) renderMessage(m);
  scrollToBottom();
  openSocket(sess.id);
}

// ── Messages ───────────────────────────────────────────────────────────

function renderMessage(m) {
  const container = $("#messages");
  const el = document.createElement("div");
  el.className = `msg ${m.role}`;
  el.dataset.id = m.id;
  el.innerHTML = `
    <div class="msg-role"></div>
    <div class="msg-content"></div>
  `;
  el.querySelector(".msg-role").textContent = m.role;
  el.querySelector(".msg-content").innerHTML = renderMarkdown(m.content || "");

  if (m.attachments?.length) {
    el.appendChild(renderAttachments(m.attachments, "Attached"));
  }
  if (m.artifacts?.length) {
    el.appendChild(renderAttachments(m.artifacts, "New / changed files"));
  }
  container.appendChild(el);
  return el;
}

function renderAttachments(items, label) {
  const wrap = document.createElement("div");
  const h = document.createElement("span");
  h.className = "attachments-label";
  h.textContent = label;
  wrap.appendChild(h);

  const row = document.createElement("div");
  row.className = "attachments";
  for (const a of items) {
    row.appendChild(renderArtifact(a));
  }
  wrap.appendChild(row);
  return wrap;
}

function renderArtifact(a) {
  const card = document.createElement("div");
  card.className = "artifact";
  const url = `/api/files?path=${encodeURIComponent(a.path)}`;
  const name = a.rel_path || a.filename || a.path;
  const mime = a.mime || "";

  if (mime.startsWith("image/")) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = name;
    img.loading = "lazy";
    card.appendChild(img);
  } else if (mime.startsWith("video/")) {
    const v = document.createElement("video");
    v.src = url;
    v.controls = true;
    card.appendChild(v);
  } else if (mime === "application/pdf") {
    const f = document.createElement("iframe");
    f.src = url;
    f.title = name;
    card.appendChild(f);
  } else {
    const a_el = document.createElement("a");
    a_el.href = url;
    a_el.target = "_blank";
    a_el.rel = "noopener";
    a_el.textContent = name;
    card.appendChild(a_el);
  }

  const meta = document.createElement("div");
  meta.className = "artifact-meta";
  meta.textContent = name + (a.size ? ` · ${formatSize(a.size)}` : "");
  card.appendChild(meta);
  return card;
}

// ── Streaming ──────────────────────────────────────────────────────────

function openSocket(sid) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/sessions/${sid}/chat`);
  state.ws = ws;

  ws.addEventListener("open", () => setConnection("connected"));
  ws.addEventListener("close", () => setConnection("disconnected"));
  ws.addEventListener("error", () => setConnection("error"));

  ws.addEventListener("message", (ev) => {
    let payload;
    try { payload = JSON.parse(ev.data); } catch { return; }
    handleEvent(payload);
  });
}

function closeSocket() {
  if (state.ws && state.ws.readyState <= 1) {
    state.ws.close();
  }
  state.ws = null;
}

function handleEvent(ev) {
  if (ev.type === "user_message") {
    renderMessage(ev.message);
    scrollToBottom();
  } else if (ev.type === "assistant_start") {
    state.streamingMessageId = ev.message_id;
    const placeholder = renderMessage({
      id: ev.message_id,
      role: "assistant",
      content: "",
      attachments: [],
      artifacts: [],
    });
    placeholder.dataset.streaming = "true";
    scrollToBottom();
  } else if (ev.type === "delta") {
    const el = document.querySelector(`.msg[data-id="${ev.message_id}"] .msg-content`);
    if (!el) return;
    // Accumulate raw text on the dataset; re-render markdown each update.
    const raw = (el.dataset.raw || "") + ev.text;
    el.dataset.raw = raw;
    el.innerHTML = renderMarkdown(raw);
    scrollToBottom(true);
  } else if (ev.type === "tool_use") {
    const msg = document.querySelector(`.msg[data-id="${ev.message_id}"]`);
    if (msg) {
      const t = document.createElement("div");
      t.className = "tool-call";
      const inp = JSON.stringify(ev.data.input || {}).slice(0, 200);
      t.textContent = `tool: ${ev.data.name}(${inp}${inp.length >= 200 ? "…" : ""})`;
      msg.appendChild(t);
    }
  } else if (ev.type === "tool_result") {
    // Skip rendering by default; full output would clutter the chat.
    // The artifacts pane on 'done' will surface created files.
  } else if (ev.type === "done") {
    const msg = document.querySelector(`.msg[data-id="${ev.message_id}"]`);
    if (msg && (ev.artifacts || []).length) {
      msg.appendChild(renderAttachments(ev.artifacts, "New / changed files"));
    }
    state.streamingMessageId = null;
    scrollToBottom();
  } else if (ev.type === "error") {
    const msg = document.querySelector(`.msg[data-id="${ev.message_id}"]`);
    if (msg) {
      msg.classList.add("error");
      const e = document.createElement("div");
      e.className = "tool-call";
      e.textContent = `error: ${ev.message}`;
      msg.appendChild(e);
    } else {
      console.error("error:", ev.message);
    }
  }
}

// ── Sending ────────────────────────────────────────────────────────────

async function sendMessage() {
  const ta = $("#input");
  const text = ta.value.trim();
  if (!text && state.staged.length === 0) return;
  if (!state.ws || state.ws.readyState !== 1) {
    alert("Not connected. Try selecting the project again.");
    return;
  }
  state.ws.send(JSON.stringify({
    type: "message",
    text,
    attachments: state.staged,
  }));
  ta.value = "";
  ta.style.height = "auto";
  state.staged = [];
  renderTray();
}

// ── Attachments ────────────────────────────────────────────────────────

async function stageFiles(fileList) {
  if (!state.activeSession) {
    alert("Select a project first.");
    return;
  }
  for (const f of fileList) {
    try {
      const meta = await api.upload(state.activeSession.id, f);
      state.staged.push(meta);
    } catch (e) {
      console.error("upload failed", e);
      alert(`Upload failed: ${e.message}`);
    }
  }
  renderTray();
}

function renderTray() {
  const tray = $("#attachment-tray");
  tray.innerHTML = "";
  if (state.staged.length === 0) {
    tray.classList.add("hidden");
    return;
  }
  tray.classList.remove("hidden");
  for (let i = 0; i < state.staged.length; i++) {
    const a = state.staged[i];
    const div = document.createElement("div");
    div.className = "tray-item";
    div.innerHTML = `
      <span></span>
      <button type="button" title="Remove">×</button>
    `;
    div.querySelector("span").textContent =
      `📎 ${a.filename} · ${formatSize(a.size)}`;
    div.querySelector("button").addEventListener("click", () => {
      state.staged.splice(i, 1);
      renderTray();
    });
    tray.appendChild(div);
  }
}

// ── Add project dialog ────────────────────────────────────────────────

async function openAddProject() {
  const dlg = $("#add-project-dialog");
  dlg.showModal();
}

// ── Markdown (tiny renderer, safe-ish) ─────────────────────────────────

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderMarkdown(text) {
  // Very small subset: code blocks (```), inline `code`, **bold**, *italic*,
  // links [text](url), and newlines. Everything is escaped first.
  let out = escapeHtml(text);
  // Code blocks
  out = out.replace(/```(\w+)?\n([\s\S]*?)```/g, (_, lang, body) => {
    return `<pre><code class="lang-${lang || "text"}">${body.replace(/\n$/, "")}</code></pre>`;
  });
  // Inline code
  out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  // Bold
  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  // Italic
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  // Links
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  );
  return out;
}

// ── Helpers ────────────────────────────────────────────────────────────

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString();
}
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function setConnection(label) {
  $("#connection-state").textContent = label;
}
function scrollToBottom(soft) {
  const c = $("#messages");
  if (soft) {
    // only autoscroll if user is already near the bottom
    if (c.scrollHeight - c.scrollTop - c.clientHeight > 200) return;
  }
  c.scrollTop = c.scrollHeight;
}

// ── Wire-up ────────────────────────────────────────────────────────────

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
}

document.addEventListener("DOMContentLoaded", async () => {
  await refreshProjects();
  if (state.projects.length > 0 && !state.activeProject) {
    await selectProject(state.projects[0].name);
  }

  $("#add-project").addEventListener("click", openAddProject);

  const dlg = $("#add-project-dialog");
  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "confirm") return;
    const data = new FormData(dlg.querySelector("form"));
    const name = data.get("name")?.toString().trim();
    const path = data.get("path")?.toString().trim();
    if (!name || !path) return;
    const tags = (data.get("tags")?.toString() || "")
      .split(",").map((s) => s.trim()).filter(Boolean);
    const description = data.get("description")?.toString() || "";
    try {
      await api.addProject({ name, path, tags, description });
      await refreshProjects();
      await selectProject(name);
    } catch (e) {
      alert(`Could not add project: ${e.message}`);
    }
    dlg.querySelector("form").reset();
  });

  $("#new-session").addEventListener("click", async () => {
    if (!state.activeProject) return;
    const sess = await api.createSession(state.activeProject);
    await selectProject(state.activeProject);
    $("#session-picker").value = sess.id;
    await openSession(sess);
  });

  $("#session-picker").addEventListener("change", async (e) => {
    const sid = e.target.value;
    const sessions = await api.listSessions(state.activeProject);
    const sess = sessions.find((s) => s.id === sid);
    if (sess) await openSession(sess);
  });

  $("#composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    await sendMessage();
  });

  const ta = $("#input");
  ta.addEventListener("input", () => autosize(ta));
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  });

  $("#file-input").addEventListener("change", async (e) => {
    await stageFiles(e.target.files);
    e.target.value = "";
  });

  // Drag-drop anywhere in window
  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth++;
    $("#drop-overlay").classList.remove("hidden");
  });
  window.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) $("#drop-overlay").classList.add("hidden");
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", async (e) => {
    e.preventDefault();
    dragDepth = 0;
    $("#drop-overlay").classList.add("hidden");
    if (e.dataTransfer.files.length) {
      await stageFiles(e.dataTransfer.files);
    }
  });

  // Reflect agent mode in footer if available later
  fetch("/api/projects").catch(() => setConnection("server unreachable"));
});
