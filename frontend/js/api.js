/* Thin client for the FastAPI backend (same origin). */
"use strict";

const Api = (() => {
  const KEY_STORE = "rag.apiKey";

  function getKey() {
    try { return sessionStorage.getItem(KEY_STORE) || localStorage.getItem(KEY_STORE) || ""; }
    catch { return ""; }
  }

  function setKey(key, remember) {
    try {
      sessionStorage.removeItem(KEY_STORE);
      localStorage.removeItem(KEY_STORE);
      if (key) (remember ? localStorage : sessionStorage).setItem(KEY_STORE, key);
    } catch { /* storage unavailable: key lives only for this page */ }
  }

  function isRemembered() {
    try { return !!localStorage.getItem(KEY_STORE); } catch { return false; }
  }

  function headers(key) {
    const h = { "Content-Type": "application/json" };
    const k = key === undefined ? getKey() : key;
    if (k) h["X-API-Key"] = k;
    return h;
  }

  async function getJson(path, key) {
    const res = await fetch(path, { headers: headers(key) });
    const body = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, body };
  }

  /** Send JSON with the given method. The session cookie rides along (same origin); an API
      key, if set, is added so key-based accounts get their own history too. */
  async function sendJson(method, path, data) {
    try {
      const res = await fetch(path, {
        method, headers: headers(),
        body: data === undefined ? undefined : JSON.stringify(data || {}),
      });
      const body = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, body };
    } catch {
      return { ok: false, status: 0, body: {} };
    }
  }

  const postJson = (path, data) => sendJson("POST", path, data || {});

  /** POST /chat. Resolves to {ok, status, body}; network failures resolve with status 0. */
  async function chat(query, signal) {
    try {
      const res = await fetch("/chat", {
        method: "POST", headers: headers(), body: JSON.stringify({ query }), signal,
      });
      const body = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, body };
    } catch (err) {
      if (err.name === "AbortError") throw err;
      return { ok: false, status: 0, body: {} };
    }
  }

  return {
    getKey, setKey, isRemembered, chat,
    info: () => getJson("/info"),
    whoami: (key) => getJson("/whoami", key),
    register: (email, password) => postJson("/auth/register", { email, password }),
    login: (email, password) => postJson("/auth/login", { email, password }),
    logout: () => postJson("/auth/logout"),
    getHistory: () => getJson("/history"),
    putHistory: (conversations) => sendJson("PUT", "/history", { conversations }),
    deleteHistory: () => sendJson("DELETE", "/history"),
  };
})();
