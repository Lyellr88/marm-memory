const API = "";
const MCP_STATUS_POLL_MS = 15_000;
let unlockedApiKey = "";

const state = {
  memoryOffset: 0,
  memoryLimit: 30,
  memoryTotal: 0,
  memorySession: "",
  logOffset: 0,
  logLimit: 30,
  logTotal: 0,
  notebookTotal: 0,
  sessions: [],
  mcpPollId: null,
};

function getStoredKey() {
  return unlockedApiKey;
}

function setStoredKey(key) {
  unlockedApiKey = key || "";
}

function authHeaders() {
  const key = getStoredKey();
  if (!key) return {};
  return { Authorization: `Bearer ${key}` };
}

function $(sel) {
  return document.querySelector(sel);
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str ?? "";
  return d.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
    ...options,
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (res.status === 401 && body?.auth_required) {
    setStoredKey("");
    showUnlock("Session expired or key required.");
    throw new Error("Authentication required");
  }
  if (!res.ok) {
    const msg = body?.detail || res.statusText || "Request failed";
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body;
}

function showUnlock(message = "") {
  document.body.classList.add("locked");
  const screen = $("#unlock-screen");
  screen.hidden = false;
  const err = $("#unlock-error");
  if (message) {
    err.textContent = message;
    err.hidden = false;
  } else {
    err.hidden = true;
  }
}

function hideUnlock() {
  document.body.classList.remove("locked");
  $("#unlock-screen").hidden = true;
  $("#unlock-error").hidden = true;
}

function setupUnlock() {
  $("#unlock-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const apiKey = String(fd.get("api_key") || "").trim();
    try {
      const res = await fetch(`${API}/api/auth/unlock`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        $("#unlock-error").textContent =
          typeof body.detail === "string" ? body.detail : "Invalid API key";
        $("#unlock-error").hidden = false;
        return;
      }
      if (body.auth_required !== false) setStoredKey(apiKey);
      hideUnlock();
      await initDashboard();
    } catch (err) {
      $("#unlock-error").textContent = err.message;
      $("#unlock-error").hidden = false;
    }
  });
}

function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

function showDetail(title, text) {
  $("#dialog-title").textContent = title;
  $("#dialog-body").textContent = text;
  $("#detail-dialog").showModal();
}

function showConfirm(title, message, confirmLabel = "Delete all") {
  return new Promise((resolve) => {
    const dialog = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    $("#confirm-ok").textContent = confirmLabel;
    dialog.returnValue = "";
    dialog.showModal();
    const handler = () => {
      dialog.removeEventListener("close", handler);
      resolve(dialog.returnValue === "confirm");
    };
    dialog.addEventListener("close", handler);
  });
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.panel;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
      document.querySelectorAll(".panel").forEach((p) => {
        const on = p.id === `panel-${panel}`;
        p.hidden = !on;
        p.classList.toggle("active", on);
      });
      if (panel === "memories") loadMemories();
      if (panel === "sessions") loadSessions();
      if (panel === "logs") loadLogs();
      if (panel === "notebook") loadNotebook();
    });
  });
}


function setHeaderStatus(mode, extraPills = "") {
  const meta = $("#header-meta");
  if (mode === "live") {
    meta.innerHTML = `<span class="pill ok">Dashboard live</span>${extraPills}`;
  } else if (mode === "offline") {
    meta.innerHTML = `<span class="pill error">Dashboard offline</span>`;
  } else if (mode === "locked") {
    meta.innerHTML = `<span class="pill muted">Unlock required</span>`;
  } else {
    meta.innerHTML = `<span class="pill muted">Connecting…</span>`;
  }
}

function embeddingPill(data) {
  if (data.semantic_model_loaded) {
    return `<span class="pill">Embeddings loaded</span>`;
  }
  if (data.embeddings_package_available) {
    return `<span class="pill muted">Embeddings available</span>`;
  }
  return `<span class="pill muted">Text search only</span>`;
}

async function probeMcpHealth() {
  const el = $("#mcp-status-dd");
  if (!el) return;
  try {
    const res = await fetch(`${API}/api/mcp-status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.reachable) {
      const ver = data.body?.version ? ` v${escapeHtml(data.body.version)}` : "";
      const status = data.body?.status ? escapeHtml(data.body.status) : "ok";
      const latency = Number.isFinite(data.latency_ms) ? `${data.latency_ms}ms` : "—";
      el.innerHTML = `
        <span class="pill ok">Reachable${ver}</span>
        <span class="hint-inline">status: ${status} &middot; ${latency} &middot; ${new Date().toLocaleTimeString()}</span>
      `;
    } else {
      throw new Error("not reachable");
    }
  } catch {
    el.innerHTML =
      `<span class="pill muted">Not on :8001</span> <span class="hint-inline">STDIO or stopped is OK &middot; ${new Date().toLocaleTimeString()}</span>`;
  }
}

function startMcpHealthPolling() {
  if (state.mcpPollId) clearInterval(state.mcpPollId);
  state.mcpPollId = setInterval(probeMcpHealth, MCP_STATUS_POLL_MS);
}

async function loadSummary() {
  const [data, health] = await Promise.all([
    api("/api/summary"),
    fetch(`${API}/health`).then((r) => r.json()).catch(() => ({})),
  ]);
  const c = data.counts;
  $("#stats-grid").innerHTML = [
    ["Memories", c.memories],
    ["Sessions", c.sessions],
    ["Log entries", c.log_entries],
    ["Notebook", c.notebook_entries],
  ]
    .map(
      ([label, n], i) => `
    <div class="stat" style="animation-delay:${i * 0.05}s">
      <strong>${n}</strong>
      <span>${escapeHtml(label)}</span>
    </div>`
    )
    .join("");

  const authLabel = health.auth_required
    ? "API key required"
    : "Localhost only (no key)";

  $("#status-dl").innerHTML = `
    <div><dt>Dashboard</dt><dd><span class="pill ok">Live on :8002</span></dd></div>
    <div><dt>MCP server</dt><dd id="mcp-status-dd">Checking…</dd></div>
    <div><dt>Database</dt><dd class="mono">${escapeHtml(data.db_path)}</dd></div>
    <div><dt>Active session</dt><dd>${escapeHtml(data.active_session || "—")}</dd></div>
    <div><dt>Auth</dt><dd>${escapeHtml(authLabel)}</dd></div>
    <div><dt>Search</dt><dd>${
      data.semantic_model_loaded
        ? "Semantic model loaded"
        : data.embeddings_package_available
          ? "Install [embeddings] for semantic search"
          : "Text search only"
    }</dd></div>
    <div><dt>Refreshed</dt><dd>${escapeHtml(new Date(data.timestamp).toLocaleString())}</dd></div>
  `;

  setHeaderStatus(
    "live",
    `${data.active_session ? `<span class="pill">Active: ${escapeHtml(data.active_session)}</span>` : ""}${embeddingPill(data)}`
  );

  probeMcpHealth();
  startMcpHealthPolling();
}

async function loadSessions() {
  const q = $("#sessions-search")?.value.trim();
  const params = q ? `?q=${encodeURIComponent(q)}` : "";
  const { items } = await api(`/api/sessions${params}`);
  state.sessions = items;

  const el = $("#sessions-list");
  if (!items.length) {
    el.innerHTML = '<p class="empty">No sessions yet. Memories and MCP tools create them automatically.</p>';
    return;
  }

  el.innerHTML = items
    .map(
      (s, i) => `
    <article class="item" style="animation-delay:${i * 0.03}s">
      <div class="item-head">
        <span class="tag session">${escapeHtml(s.session_name)}</span>
        ${s.marm_active ? '<span class="tag">MARM active</span>' : ""}
      </div>
      <p class="item-meta">
        ${s.memory_count} memories · ${s.log_count} logs · last ${escapeHtml(formatDate(s.last_accessed))}
      </p>
      <div class="item-actions">
        <button type="button" class="btn sm" data-view-memories>View memories</button>
        <button type="button" class="btn sm danger" data-del-session="${escapeHtml(s.session_name)}">Delete session</button>
      </div>
    </article>`
    )
    .join("");

  el.querySelectorAll("[data-view-memories]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".item");
      const sessionName = card.querySelector(".tag.session")?.textContent || "";
      state.memorySession = sessionName;
      document.querySelector('.tab[data-panel="memories"]').click();
    });
  });

  el.querySelectorAll("[data-del-session]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.delSession;
      const ok = await showConfirm(
        `Delete session "${name}"?`,
        "This removes the session record. Memories and logs for this session are not deleted.",
        "Delete session"
      );
      if (!ok) return;
      try {
        await api(`/api/sessions/${encodeURIComponent(name)}`, { method: "DELETE" });
        toast(`Session "${name}" deleted`);
        loadSessions();
        loadSummary();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
}

function updateSessionChip() {
  const chip = $("#memory-session-chip");
  const label = $("#memory-session-chip-label");
  if (state.memorySession) {
    label.textContent = state.memorySession;
    chip.hidden = false;
  } else {
    chip.hidden = true;
  }
}

async function loadMemories(reset = true) {
  if (reset) state.memoryOffset = 0;
  const q = $("#memory-search").value.trim();
  const params = new URLSearchParams({
    limit: state.memoryLimit,
    offset: state.memoryOffset,
  });
  if (state.memorySession) params.set("session", state.memorySession);
  if (q) params.set("q", q);
  updateSessionChip();

  const data = await api(`/api/memories?${params}`);
  state.memoryTotal = data.total;

  const el = $("#memories-list");
  if (!data.items.length) {
    el.innerHTML = '<p class="empty">No memories match. Add one or clear filters.</p>';
  } else {
    el.innerHTML = data.items
      .map(
        (m, i) => `
      <article class="item" style="animation-delay:${i * 0.02}s">
        <div class="item-head">
          <span class="tag session">${escapeHtml(m.session_name)}</span>
          <span class="tag">${escapeHtml(m.context_type)}</span>
        </div>
        <p>${escapeHtml(m.display_preview ?? m.preview)}</p>
        <p class="item-meta">${escapeHtml(formatDate(m.timestamp))} · id ${escapeHtml(m.id.slice(0, 8))}…</p>
        <div class="item-actions">
          <button type="button" class="btn sm" data-view-memory="${escapeHtml(m.id)}">View</button>
          <button type="button" class="btn sm" data-edit-memory="${escapeHtml(m.id)}">Edit</button>
          <button type="button" class="btn sm danger" data-del-memory="${escapeHtml(m.id)}">Delete</button>
        </div>
      </article>`
      )
      .join("");

    const byId = Object.fromEntries(data.items.map((m) => [m.id, m]));
    el.querySelectorAll("[data-view-memory]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const m = byId[btn.dataset.viewMemory];
        showDetail(
          `${m.session_name} · ${m.context_type}`,
          m.display_content ?? m.content
        );
      });
    });
    el.querySelectorAll("[data-edit-memory]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const m = byId[btn.dataset.editMemory];
        const form = $("#memory-add-form");
        form.dataset.editingId = m.id;
        form.querySelector("h3").textContent = "Edit memory";
        form.elements.namedItem("session_name").value = m.session_name;
        form.elements.namedItem("session_name").readOnly = true;
        form.elements.namedItem("context_type").value = m.context_type;
        form.elements.namedItem("content").value = m.display_content ?? m.content;
        form.hidden = false;
        form.elements.namedItem("content").focus();
      });
    });

    el.querySelectorAll("[data-del-memory]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this memory permanently?")) return;
        try {
          await api(`/api/memories/${btn.dataset.delMemory}`, { method: "DELETE" });
          toast("Memory deleted");
          loadMemories(true);
          loadSummary();
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
  }

  const pager = $("#memories-pager");
  const end = Math.min(state.memoryOffset + data.items.length, data.total);
  const start = data.total === 0 ? 0 : state.memoryOffset + 1;
  pager.innerHTML = `
    <button type="button" class="btn sm" id="mem-prev" ${state.memoryOffset <= 0 ? "disabled" : ""}>Prev</button>
    <span>${start}–${end} of ${data.total}</span>
    <button type="button" class="btn sm" id="mem-next" ${end >= data.total ? "disabled" : ""}>Next</button>
  `;
  $("#mem-prev")?.addEventListener("click", () => {
    state.memoryOffset = Math.max(0, state.memoryOffset - state.memoryLimit);
    loadMemories(false);
  });
  $("#mem-next")?.addEventListener("click", () => {
    state.memoryOffset += state.memoryLimit;
    loadMemories(false);
  });
}

async function loadLogs(reset = true) {
  if (reset) state.logOffset = 0;
  const q = $("#log-search")?.value.trim();
  const params = new URLSearchParams({
    limit: state.logLimit,
    offset: state.logOffset,
  });
  if (q) params.set("q", q);
  const data = await api(`/api/logs?${params}`);
  state.logTotal = data.total;
  const el = $("#logs-list");

  if (!data.items.length) {
    el.innerHTML = '<p class="empty">No protocol log entries.</p>';
  } else {
    el.innerHTML = data.items
      .map(
        (l, i) => `
    <article class="item" style="animation-delay:${i * 0.02}s">
      <div class="item-head">
        <span class="tag session">${escapeHtml(l.session_name)}</span>
        <span class="tag">${escapeHtml(l.entry_date ? new Date(l.entry_date).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—")}</span>
        <span class="tag">${escapeHtml(l.topic)}</span>
      </div>
      <p>${escapeHtml(l.display_summary ?? l.summary)}</p>
      <div class="item-actions">
        <button type="button" class="btn sm" data-view-log="${escapeHtml(l.id)}">Full entry</button>
        <button type="button" class="btn sm danger" data-del-log="${escapeHtml(l.id)}">Delete</button>
      </div>
    </article>`
      )
      .join("");

    const byId = Object.fromEntries(data.items.map((l) => [l.id, l]));
    el.querySelectorAll("[data-view-log]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const l = byId[btn.dataset.viewLog];
        showDetail(
          `${l.session_name} · ${l.topic}`,
          l.display_full_entry ?? l.full_entry
        );
      });
    });
    el.querySelectorAll("[data-del-log]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Delete this log entry?")) return;
        try {
          await api(`/api/logs/${btn.dataset.delLog}`, { method: "DELETE" });
          toast("Log deleted");
          loadLogs(true);
          loadSummary();
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
  }

  const pager = $("#logs-pager");
  const end = Math.min(state.logOffset + data.items.length, data.total);
  const start = data.total === 0 ? 0 : state.logOffset + 1;
  pager.innerHTML = `
    <button type="button" class="btn sm" id="log-prev" ${state.logOffset <= 0 ? "disabled" : ""}>Prev</button>
    <span>${start}–${end} of ${data.total}</span>
    <button type="button" class="btn sm" id="log-next" ${end >= data.total ? "disabled" : ""}>Next</button>
  `;
  $("#log-prev")?.addEventListener("click", () => {
    state.logOffset = Math.max(0, state.logOffset - state.logLimit);
    loadLogs(false);
  });
  $("#log-next")?.addEventListener("click", () => {
    state.logOffset += state.logLimit;
    loadLogs(false);
  });
}

async function loadNotebook() {
  const q = $("#notebook-search")?.value.trim();
  const params = q ? `?q=${encodeURIComponent(q)}` : "";
  const { items } = await api(`/api/notebook${params}`);
  state.notebookTotal = items.length;
  const el = $("#notebook-list");
  if (!items.length) {
    el.innerHTML = '<p class="empty">Notebook is empty.</p>';
    return;
  }

  el.innerHTML = items
    .map(
      (n, i) => `
    <article class="item" style="animation-delay:${i * 0.02}s">
      <div class="item-head"><span class="tag session">${escapeHtml(n.name)}</span></div>
      <p>${escapeHtml(n.display_preview ?? n.preview)}</p>
      <p class="item-meta">${n.size_chars} chars · updated ${escapeHtml(formatDate(n.updated_at))}</p>
      <div class="item-actions">
        <button type="button" class="btn sm" data-view-nb="${escapeHtml(n.name)}">View</button>
        <button type="button" class="btn sm" data-edit-nb="${escapeHtml(n.name)}">Edit</button>
        <button type="button" class="btn sm danger" data-del-nb="${escapeHtml(n.name)}">Delete</button>
      </div>
    </article>`
    )
    .join("");

  const byName = Object.fromEntries(items.map((n) => [n.name, n]));
  el.querySelectorAll("[data-view-nb]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = byName[btn.dataset.viewNb];
      showDetail(n.name, n.data);
    });
  });
  el.querySelectorAll("[data-edit-nb]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const n = byName[btn.dataset.editNb];
      const form = $("#notebook-form");
      form.hidden = false;
      form.elements.namedItem("name").value = n.name;
      form.elements.namedItem("name").readOnly = true;
      form.elements.namedItem("data").value = n.data;
    });
  });
  el.querySelectorAll("[data-del-nb]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Delete notebook entry "${btn.dataset.delNb}"?`)) return;
      try {
        await api(`/api/notebook/${encodeURIComponent(btn.dataset.delNb)}`, {
          method: "DELETE",
        });
        toast("Notebook entry deleted");
        loadNotebook();
        loadSummary();
      } catch (e) {
        toast(e.message, true);
      }
    });
  });
}

function setupForms() {
  function resetMemoryForm() {
    const form = $("#memory-add-form");
    delete form.dataset.editingId;
    form.querySelector("h3").textContent = "New memory";
    form.elements.namedItem("session_name").readOnly = false;
    form.reset();
    form.hidden = true;
  }

  $("#memory-add-toggle").addEventListener("click", () => {
    const form = $("#memory-add-form");
    if (!form.hidden && !form.dataset.editingId) { resetMemoryForm(); return; }
    resetMemoryForm();
    form.hidden = false;
    form.elements.namedItem("session_name").focus();
  });
  $("#memory-add-cancel").addEventListener("click", resetMemoryForm);

  $("#memory-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const editingId = e.target.dataset.editingId;
    try {
      if (editingId) {
        await api(`/api/memories/${editingId}`, {
          method: "PUT",
          body: JSON.stringify({
            content: fd.get("content"),
            context_type: fd.get("context_type"),
          }),
        });
        toast("Memory updated");
      } else {
        await api("/api/memories", {
          method: "POST",
          body: JSON.stringify({
            content: fd.get("content"),
            session_name: fd.get("session_name"),
            context_type: fd.get("context_type"),
          }),
        });
        toast("Memory saved");
        loadSessions();
      }
      resetMemoryForm();
      loadMemories(true);
      loadSummary();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#memory-session-chip-clear").addEventListener("click", () => {
    state.memorySession = "";
    loadMemories(true);
  });

  $("#memory-delete-all").addEventListener("click", async () => {
    const count = state.memoryTotal;
    const ok = await showConfirm(
      `Delete ${count} ${count === 1 ? "memory" : "memories"}?`,
      "This will permanently delete all memories across all sessions. This cannot be undone."
    );
    if (!ok) return;
    try {
      const res = await api("/api/memories", { method: "DELETE" });
      toast(`Deleted ${res.count} memories`);
      loadMemories(true);
      loadSummary();
      loadSessions();
    } catch (e) {
      toast(e.message, true);
    }
  });

  $("#sessions-delete-all").addEventListener("click", async () => {
    const count = state.sessions.length;
    const ok = await showConfirm(
      `Delete ${count} ${count === 1 ? "session" : "sessions"}?`,
      "This removes all session records. Memories and logs are not deleted."
    );
    if (!ok) return;
    try {
      const res = await api("/api/sessions", { method: "DELETE" });
      toast(`Deleted ${res.count} sessions`);
      loadSessions();
      loadSummary();
    } catch (e) {
      toast(e.message, true);
    }
  });

  $("#notebook-delete-all").addEventListener("click", async () => {
    const count = state.notebookTotal;
    const ok = await showConfirm(
      `Delete ${count} notebook ${count === 1 ? "entry" : "entries"}?`,
      "This will permanently delete all notebook entries. This cannot be undone."
    );
    if (!ok) return;
    try {
      const res = await api("/api/notebook", { method: "DELETE" });
      toast(`Deleted ${res.count} notebook entries`);
      loadNotebook();
      loadSummary();
    } catch (e) {
      toast(e.message, true);
    }
  });

  let searchTimer;
  $("#memory-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadMemories(true), 300);
  });
  $("#memory-refresh").addEventListener("click", () => loadMemories(true));

  let sessionsSearchTimer;
  $("#sessions-search").addEventListener("input", () => {
    clearTimeout(sessionsSearchTimer);
    sessionsSearchTimer = setTimeout(() => loadSessions(), 300);
  });
  $("#sessions-refresh").addEventListener("click", () => loadSessions());

  $("#sessions-add-toggle").addEventListener("click", () => {
    const form = $("#session-add-form");
    form.hidden = false;
    form.elements.namedItem("session_name").focus();
  });
  $("#sessions-add-cancel").addEventListener("click", () => {
    $("#session-add-form").hidden = true;
  });
  $("#session-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ session_name: fd.get("session_name") }),
      });
      toast("Session created");
      e.target.reset();
      e.target.hidden = true;
      loadSessions();
      loadSummary();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#logs-refresh").addEventListener("click", () => loadLogs(true));

  let logSearchTimer;
  $("#log-search").addEventListener("input", () => {
    clearTimeout(logSearchTimer);
    logSearchTimer = setTimeout(() => loadLogs(true), 300);
  });

  $("#logs-delete-all").addEventListener("click", async () => {
    const count = state.logTotal;
    const ok = await showConfirm(
      `Delete ${count} log ${count === 1 ? "entry" : "entries"}?`,
      "This will permanently delete all protocol log entries. This cannot be undone."
    );
    if (!ok) return;
    try {
      const res = await api("/api/logs", { method: "DELETE" });
      toast(`Deleted ${res.count} log entries`);
      loadLogs(true);
      loadSummary();
    } catch (e) {
      toast(e.message, true);
    }
  });

  let notebookSearchTimer;
  $("#notebook-search").addEventListener("input", () => {
    clearTimeout(notebookSearchTimer);
    notebookSearchTimer = setTimeout(() => loadNotebook(), 300);
  });

  $("#notebook-add-toggle").addEventListener("click", () => {
    const form = $("#notebook-form");
    form.hidden = false;
    form.reset();
    form.elements.namedItem("name").readOnly = false;
    form.elements.namedItem("name").focus();
  });
  $("#notebook-cancel").addEventListener("click", () => {
    $("#notebook-form").hidden = true;
  });
  $("#notebook-refresh").addEventListener("click", loadNotebook);

  $("#notebook-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/api/notebook", {
        method: "POST",
        body: JSON.stringify({ name: fd.get("name"), data: fd.get("data") }),
      });
      toast("Notebook saved");
      e.target.hidden = true;
      loadNotebook();
      loadSummary();
    } catch (err) {
      toast(err.message, true);
    }
  });
}

async function initDashboard() {
  try {
    await loadSummary();
  } catch (e) {
    if (e.message === "Authentication required") return;
    setHeaderStatus("offline");
    $("#stats-grid").innerHTML = "";
    $("#status-dl").innerHTML = `<p class="empty">${escapeHtml(e.message)}</p>`;
    toast(e.message, true);
    return;
  }
  try {
    await loadSessions();
  } catch (e) {
    toast(`Could not load sessions: ${e.message}`, true);
  }
}

async function init() {
  setupTabs();
  setupForms();
  setupUnlock();

  const health = await fetch(`${API}/health`).then((r) => r.json()).catch(() => ({}));
  $("#loading-screen").hidden = true;

  if (health.auth_required && !getStoredKey()) {
    setHeaderStatus("locked");
    showUnlock();
    return;
  }

  if (health.auth_required && getStoredKey()) {
    const check = await fetch(`${API}/api/summary`, { headers: authHeaders() });
    if (check.status === 401) {
      setHeaderStatus("locked");
      showUnlock("Invalid or expired key.");
      return;
    }
  }

  hideUnlock();
  await initDashboard();
}

init();
