/* Chat UI state: conversations, sending, settings, theme. Each question is sent to the
   pipeline on its own (the security pipeline is single-turn by design). */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const HISTORY_KEY = "rag.conversations";
  const SAVE_KEY = "rag.saveHistory";
  const THEME_KEY = "rag.theme";
  const MAX_CONVERSATIONS = 50;

  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* quota / disabled */ } },
    del(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
  };

  const state = {
    saveHistory: store.get(SAVE_KEY, true),
    conversations: [],
    currentId: null,
    busy: false,
    maxChars: 4000,
  };
  state.conversations = state.saveHistory ? store.get(HISTORY_KEY, []) : [];

  const els = {
    app: $("app"), sidebar: $("sidebar"), scrim: $("scrim"), convList: $("convList"), messages: $("messages"),
    empty: $("emptyState"), input: $("input"), send: $("sendBtn"), composer: $("composer"), charCount: $("charCount"),
    title: $("chatTitle"), status: $("statusPill"), model: $("modelLabel"), identityUser: $("identityUser"),
    identityMeta: $("identityMeta"), identityDot: $("identityDot"), dialog: $("settingsDialog"), toast: $("toast"),
  };

  /* ---------------- helpers ---------------- */
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random()));
  const current = () => state.conversations.find((c) => c.id === state.currentId) || null;

  function persist() {
    state.conversations = state.conversations.slice(0, MAX_CONVERSATIONS);
    if (state.saveHistory) store.set(HISTORY_KEY, state.conversations);
  }

  let toastTimer;
  function notify(msg) {
    els.toast.textContent = msg; els.toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { els.toast.hidden = true; }, 2200);
  }

  const BOT_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z"/><path d="m8.5 12 2.5 2.5 4.5-5" fill="none"/></svg>';
  const DOC_ICON = '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5"/></svg>';
  const SHIELD_ICON = '<svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z"/></svg>';
  const COPY_ICON = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';

  /* ---------------- theme ---------------- */
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }
  function initialTheme() {
    const saved = store.get(THEME_KEY, null);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  $("themeBtn").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next); store.set(THEME_KEY, next);
    renderConversation();   // charts and diagrams pick up the new palette
  });

  /* ---------------- sidebar ---------------- */
  function groupLabel(ts) {
    const days = (Date.now() - ts) / 86400000;
    if (new Date(ts).toDateString() === new Date().toDateString()) return "Today";
    if (days < 7) return "Previous 7 days";
    return "Older";
  }

  function renderSidebar() {
    els.convList.innerHTML = "";
    if (!state.conversations.length) {
      els.convList.appendChild(Object.assign(document.createElement("div"), {
        className: "conv-empty", textContent: state.saveHistory ? "No conversations yet." : "History saving is off.",
      }));
      return;
    }
    let lastGroup = null;
    for (const conv of state.conversations) {
      const g = groupLabel(conv.updated);
      if (g !== lastGroup) {
        const h = document.createElement("div"); h.className = "conv-group"; h.textContent = g;
        els.convList.appendChild(h); lastGroup = g;
      }
      const item = document.createElement("div");
      item.className = "conv-item" + (conv.id === state.currentId ? " active" : "");
      item.setAttribute("role", "button"); item.tabIndex = 0;
      const title = document.createElement("span"); title.className = "conv-title"; title.textContent = conv.title;
      const del = document.createElement("button");
      del.className = "conv-del"; del.type = "button"; del.setAttribute("aria-label", "Delete conversation");
      del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>';
      del.addEventListener("click", (e) => { e.stopPropagation(); deleteConversation(conv.id); });
      item.append(title, del);
      const open = () => { state.currentId = conv.id; renderAll(); closeNav(); };
      item.addEventListener("click", open);
      item.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      els.convList.appendChild(item);
    }
  }

  function deleteConversation(id) {
    state.conversations = state.conversations.filter((c) => c.id !== id);
    if (state.currentId === id) state.currentId = null;
    persist(); renderAll();
  }

  /* ---------------- messages ---------------- */
  function userNode(msg) {
    const row = document.createElement("div"); row.className = "msg msg-user";
    const b = document.createElement("div"); b.className = "bubble"; b.textContent = msg.content;
    row.appendChild(b);
    return row;
  }

  function botNode(msg) {
    const row = document.createElement("div");
    row.className = "msg msg-bot" + (msg.status === "blocked" ? " blocked" : msg.status === "error" ? " error" : "");
    const avatar = document.createElement("div"); avatar.className = "avatar"; avatar.innerHTML = BOT_ICON;
    const body = document.createElement("div"); body.className = "body";
    const content = document.createElement("div"); content.className = "content";
    body.appendChild(content);

    if (msg.status === "ok") {
      Render.renderAnswer(content, msg.content, msg.citations, notify);
    } else {
      content.textContent = msg.content;
      if (msg.hint) {
        const hint = document.createElement("div"); hint.className = "msg-meta"; hint.textContent = msg.hint;
        body.appendChild(hint);
      }
    }

    const meta = document.createElement("div"); meta.className = "msg-meta";
    if (msg.status === "blocked") {
      const chip = document.createElement("span"); chip.className = "chip";
      chip.innerHTML = SHIELD_ICON; chip.append("Stopped by a security check");
      meta.appendChild(chip);
    }
    for (const src of msg.sources || []) {
      const chip = document.createElement("span"); chip.className = "chip";
      chip.innerHTML = DOC_ICON; chip.append(src);
      meta.appendChild(chip);
    }
    const spacer = document.createElement("span"); spacer.className = "spacer"; meta.appendChild(spacer);
    if (msg.latency) {
      const t = document.createElement("span"); t.textContent = `${(msg.latency / 1000).toFixed(1)}s`; meta.appendChild(t);
    }
    if (msg.status === "ok") {
      const copy = document.createElement("button"); copy.type = "button"; copy.className = "meta-btn";
      copy.innerHTML = COPY_ICON + "<span>Copy</span>";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(msg.content); notify("Answer copied"); } catch { notify("Couldn't copy"); }
      });
      meta.appendChild(copy);
    }
    body.appendChild(meta);
    row.append(avatar, body);
    return row;
  }

  function typingNode() {
    const row = document.createElement("div"); row.className = "msg msg-bot"; row.id = "typing";
    const avatar = document.createElement("div"); avatar.className = "avatar"; avatar.innerHTML = BOT_ICON;
    const body = document.createElement("div"); body.className = "body";
    body.innerHTML = '<div class="typing"><span class="dots"><i></i><i></i><i></i></span><span id="typingText">Running security checks…</span></div>';
    row.append(avatar, body);
    return row;
  }

  function renderConversation() {
    els.messages.querySelectorAll(".msg-bot .content").forEach((c) => Render.destroy(c));
    els.messages.querySelectorAll(".msg").forEach((n) => n.remove());
    const conv = current();
    els.empty.hidden = !!(conv && conv.messages.length);
    els.title.textContent = conv ? conv.title : "New chat";
    if (conv) for (const m of conv.messages) els.messages.appendChild(m.role === "user" ? userNode(m) : botNode(m));
    if (state.busy) els.messages.appendChild(typingNode());
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function renderAll() { renderSidebar(); renderConversation(); updateComposer(); }

  /* ---------------- sending ---------------- */
  function interpret(res) {
    const body = res.body || {};
    const base = { role: "assistant", ts: Date.now(), latency: body.latency_ms || 0, sources: [], citations: {} };
    if (res.status === 0) return { ...base, status: "error", content: "Can't reach the assistant server.",
      hint: "Start it with `uvicorn api.main:app` and reload this page." };
    if (res.status === 401) { setTimeout(openSettings, 300);
      return { ...base, status: "error", content: "Your API key was rejected. Update it in Settings." }; }
    if (res.status === 422) return { ...base, status: "error", content: "That message couldn't be sent (it may be too long)." };
    if (res.status === 429) return { ...base, status: "blocked", content: body.response || "Too many requests. Please wait a moment." };
    if (res.status === 503) return { ...base, status: "error", content: body.response || "The assistant is temporarily unavailable.",
      hint: "If you're using a local LLM, check that it's running (e.g. `ollama serve`) and the model is pulled." };
    if (!res.ok) return { ...base, status: "error", content: "Something went wrong. Please try again." };
    if (body.blocked) return { ...base, status: "blocked", content: body.response };
    return { ...base, status: "ok", content: body.response || "", sources: body.sources || [], citations: body.citations || {} };
  }

  async function send(text) {
    const query = text.trim();
    if (!query || state.busy) return;
    let conv = current();
    if (!conv) {
      conv = { id: uid(), title: query.length > 48 ? query.slice(0, 47) + "…" : query, messages: [], updated: Date.now() };
      state.conversations.unshift(conv); state.currentId = conv.id;
    }
    conv.messages.push({ role: "user", content: query, ts: Date.now() });
    conv.updated = Date.now();
    state.conversations = [conv, ...state.conversations.filter((c) => c.id !== conv.id)];
    els.input.value = ""; autosize();
    state.busy = true; persist(); renderAll();

    const started = Date.now();
    const ticker = setInterval(() => {
      const t = document.getElementById("typingText");
      if (!t) return;
      const s = Math.round((Date.now() - started) / 1000);
      t.textContent = (s < 3 ? "Running security checks…" : "Retrieving and generating…") + (s >= 2 ? ` ${s}s` : "");
    }, 500);

    let reply;
    try { reply = interpret(await Api.chat(query)); }
    finally { clearInterval(ticker); }
    reply.latency = reply.latency || Date.now() - started;
    conv.messages.push(reply);
    conv.updated = Date.now();
    state.busy = false; persist(); renderAll();
    els.input.focus();
  }

  /* ---------------- composer ---------------- */
  function autosize() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
  }
  function updateComposer() {
    const n = els.input.value.length;
    els.charCount.textContent = `${n} / ${state.maxChars}`;
    els.send.disabled = state.busy || !els.input.value.trim() || n > state.maxChars;
    els.input.disabled = state.busy;
  }
  els.input.addEventListener("input", () => { autosize(); updateComposer(); });
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(els.input.value); }
  });
  els.composer.addEventListener("submit", (e) => { e.preventDefault(); send(els.input.value); });
  $("suggestions").addEventListener("click", (e) => {
    const b = e.target.closest(".suggestion");
    if (b) send(b.getAttribute("data-q"));
  });
  $("newChatBtn").addEventListener("click", () => { state.currentId = null; renderAll(); closeNav(); els.input.focus(); });

  /* ---------------- mobile nav ---------------- */
  function closeNav() { els.app.classList.remove("nav-open"); }
  $("menuBtn").addEventListener("click", () => els.app.classList.add("nav-open"));
  els.scrim.addEventListener("click", closeNav);

  /* ---------------- identity / status ---------------- */
  async function refreshIdentity(key) {
    try {
      const res = await Api.whoami(key);
      if (res.ok) {
        const b = res.body;
        els.identityUser.textContent = b.authenticated ? b.user_id : "Guest";
        els.identityMeta.textContent = `role: ${b.role} · tenant: ${b.tenant_id}`;
        els.identityDot.className = "dot ok";
        return { ok: true, body: b };
      }
      els.identityUser.textContent = res.status === 401 ? "Invalid API key" : "Not connected";
      els.identityMeta.textContent = res.status === 401 ? "open Settings to fix" : "—";
      els.identityDot.className = "dot bad";
      return { ok: false, status: res.status };
    } catch {
      els.identityUser.textContent = "Server offline"; els.identityMeta.textContent = "—"; els.identityDot.className = "dot bad";
      return { ok: false, status: 0 };
    }
  }

  async function refreshStatus() {
    try {
      const res = await Api.info();
      if (!res.ok) throw new Error();
      els.model.textContent = `model: ${res.body.model}`;
      els.model.title = res.body.model;
      state.maxChars = res.body.max_query_chars || 4000;
      els.input.maxLength = state.maxChars;
      els.status.textContent = "online"; els.status.className = "pill ok";
    } catch {
      els.status.textContent = "offline"; els.status.className = "pill bad";
    }
    updateComposer();
  }

  /* ---------------- settings ---------------- */
  function openSettings() {
    $("apiKeyInput").value = Api.getKey();
    $("rememberKey").checked = Api.isRemembered();
    $("saveHistory").checked = state.saveHistory;
    $("testResult").textContent = ""; $("testResult").className = "test-result";
    if (!els.dialog.open) els.dialog.showModal();
  }
  $("settingsBtn").addEventListener("click", () => { openSettings(); closeNav(); });

  $("testKeyBtn").addEventListener("click", async () => {
    const out = $("testResult");
    out.textContent = "Testing…"; out.className = "test-result";
    const r = await refreshIdentity($("apiKeyInput").value.trim());
    if (r.ok) { out.textContent = `Connected as ${r.body.user_id} (${r.body.role})`; out.className = "test-result ok"; }
    else { out.textContent = r.status === 401 ? "Key rejected" : "Server unreachable"; out.className = "test-result bad"; }
    refreshIdentity();   // restore the badge to the saved key
  });

  $("clearHistoryBtn").addEventListener("click", () => {
    if (!confirm("Delete all saved conversations from this browser?")) return;
    state.conversations = []; state.currentId = null; store.del(HISTORY_KEY);
    renderAll(); notify("Chat history deleted");
  });

  $("settingsForm").addEventListener("submit", (e) => {
    if (e.submitter && e.submitter.value !== "save") return;
    Api.setKey($("apiKeyInput").value.trim(), $("rememberKey").checked);
    state.saveHistory = $("saveHistory").checked;
    store.set(SAVE_KEY, state.saveHistory);
    if (state.saveHistory) persist(); else store.del(HISTORY_KEY);
    refreshIdentity(); renderSidebar(); notify("Settings saved");
  });

  /* ---------------- boot ---------------- */
  applyTheme(initialTheme());
  renderAll();
  refreshStatus();
  refreshIdentity();
  els.input.focus();
})();
