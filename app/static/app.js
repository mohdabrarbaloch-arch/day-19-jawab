/* Jawab frontend — vanilla, no build step, no framework.
   The whole app is: hold a token, render threads, render cited answers. */

(() => {
  "use strict";

  const API = "/api";
  const TOKEN_KEY = "jawab.token";
  const USER_KEY = "jawab.user";

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
    threadId: null,
    threads: [],
    busy: false,
  };

  // ── tiny helpers ────────────────────────────────────────────

  function toast(msg, ms = 2600) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    requestAnimationFrame(() => t.classList.add("is-visible"));
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      t.classList.remove("is-visible");
      setTimeout(() => (t.hidden = true), 220);
    }, ms);
  }

  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const res = await fetch(API + path, { ...opts, headers });

    if (res.status === 401 && state.token) {
      signOut(true);
      throw new Error("Your session expired. Please sign in again.");
    }

    if (res.status === 204) return null;

    let body = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      body = await res.json().catch(() => null);
    }

    if (!res.ok) {
      const detail =
        (body && (body.detail || body.message)) || `Request failed (${res.status})`;
      throw new Error(typeof detail === "string" ? detail : "Request failed");
    }
    return body;
  }

  function initials(name) {
    const s = (name || "?").trim();
    if (!s) return "?";
    const parts = s.split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }

  function domainOf(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return url;
    }
  }

  // ── auth ────────────────────────────────────────────────────

  let authMode = "login";

  function setAuthMode(mode) {
    authMode = mode;
    document.querySelectorAll(".auth-tab").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.mode === mode);
    });
    $("#name-field").hidden = mode !== "register";
    $("#auth-submit").textContent = mode === "register" ? "Create account" : "Sign in";
    const pw = $("#auth-form [name=password]");
    pw.autocomplete = mode === "register" ? "new-password" : "current-password";
    $("#auth-error").hidden = true;
  }

  function showAuthError(msg) {
    const box = $("#auth-error");
    box.textContent = msg;
    box.hidden = false;
  }

  async function submitAuth(e) {
    e.preventDefault();
    const form = e.target;
    const btn = $("#auth-submit");
    const data = {
      email: form.email.value.trim(),
      password: form.password.value,
    };
    if (authMode === "register") {
      data.display_name = form.display_name.value.trim();
    }

    btn.disabled = true;
    btn.textContent = authMode === "register" ? "Creating…" : "Signing in…";

    try {
      const path = authMode === "register" ? "/auth/register" : "/auth/login";
      const out = await api(path, { method: "POST", body: JSON.stringify(data) });
      state.token = out.access_token;
      state.user = out.user;
      localStorage.setItem(TOKEN_KEY, state.token);
      localStorage.setItem(USER_KEY, JSON.stringify(state.user));
      enterApp();
    } catch (err) {
      showAuthError(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = authMode === "register" ? "Create account" : "Sign in";
    }
  }

  function signOut(silent) {
    state.token = "";
    state.user = null;
    state.threadId = null;
    state.threads = [];
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    $("#app").hidden = true;
    $("#auth-screen").hidden = false;
    $("#conversation").hidden = true;
    $("#conversation").innerHTML = "";
    $("#hero").hidden = false;
    if (!silent) toast("Signed out");
  }

  function enterApp() {
    $("#auth-screen").hidden = true;
    $("#app").hidden = false;

    const name = state.user.display_name || state.user.email.split("@")[0];
    $("#user-name").textContent = name;
    $("#user-email").textContent = state.user.email;
    $("#user-avatar").textContent = initials(name);

    loadThreads();
    $("#question").focus();
  }

  // ── threads ─────────────────────────────────────────────────

  async function loadThreads() {
    try {
      state.threads = await api("/threads?limit=60");
    } catch {
      state.threads = [];
    }
    renderThreads();
  }

  function renderThreads() {
    const list = $("#thread-list");
    list.innerHTML = "";

    if (!state.threads.length) {
      list.appendChild(
        el("div", "thread-empty", "No searches yet. Ask something and it'll show up here.")
      );
      return;
    }

    for (const t of state.threads) {
      const item = el("button", "thread-item");
      item.type = "button";
      if (t.id === state.threadId) item.classList.add("is-active");

      const title = el("span", "t-title", t.title || "Untitled");
      const del = el("span", "t-del", "×");
      del.title = "Delete";
      del.setAttribute("role", "button");
      del.setAttribute("aria-label", "Delete search");

      del.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        try {
          await api(`/threads/${t.id}`, { method: "DELETE" });
          state.threads = state.threads.filter((x) => x.id !== t.id);
          if (state.threadId === t.id) newThread();
          renderThreads();
          toast("Search deleted");
        } catch (err) {
          toast(err.message);
        }
      });

      item.append(title, del);
      item.addEventListener("click", () => openThread(t.id));
      list.appendChild(item);
    }
  }

  function newThread() {
    state.threadId = null;
    $("#conversation").innerHTML = "";
    $("#conversation").hidden = true;
    $("#hero").hidden = false;
    $("#topbar-title").textContent = "New search";
    renderThreads();
    closeSidebar();
    $("#question").focus();
  }

  async function openThread(id) {
    closeSidebar();
    try {
      const thread = await api(`/threads/${id}`);
      state.threadId = thread.id;
      $("#topbar-title").textContent = thread.title || "Search";
      $("#hero").hidden = true;

      const conv = $("#conversation");
      conv.innerHTML = "";
      conv.hidden = false;

      for (const q of thread.queries) {
        conv.appendChild(renderTurn(q));
      }

      renderThreads();
      scrollToBottom();
    } catch (err) {
      toast(err.message);
    }
  }

  // ── rendering a turn ────────────────────────────────────────

  function renderTurn(q) {
    const turn = el("div", "turn");

    // question
    const qRow = el("div", "turn-q");
    const av = el("div", "q-avatar", initials(state.user?.display_name || state.user?.email));
    const qText = el("div", "q-text", q.question);
    qRow.append(av, qText);
    turn.appendChild(qRow);

    // answer
    turn.appendChild(renderAnswer(q));
    return turn;
  }

  function renderAnswer(q) {
    const card = el("div", "answer");

    if (q.summary) {
      card.appendChild(el("p", "answer-summary", q.summary));
    }

    const body = el("div", "answer-body");
    const sentences = q.sentences && q.sentences.length
      ? q.sentences
      : [{ text: q.answer || "", source_index: 0 }];

    if (!q.answer) {
      const empty = el("div", "answer-error");
      empty.textContent =
        "I couldn't build an answer from the pages I found. Try rephrasing, or ask something more specific.";
      card.appendChild(empty);
    } else {
      sentences.forEach((s, i) => {
        if (!s.text) return;
        const span = el("span", "sent", s.text + " ");
        const src = (q.sources || []).find((x) => x.rank === s.source_index);
        if (src) {
          const chip = el("a", "cite", String(src.rank + 1));
          chip.href = src.url;
          chip.target = "_blank";
          chip.rel = "noopener noreferrer";
          chip.title = src.title || src.domain;
          span.appendChild(chip);
        }
        body.appendChild(span);
        if (i < sentences.length - 1) body.appendChild(document.createTextNode(" "));
      });
      card.appendChild(body);
    }

    // meta
    const meta = el("div", "answer-meta");
    const conf = Math.round((q.confidence || 0) * 100);
    const confPill = el("span", "pill", `${conf}% confidence`);
    confPill.classList.add(conf >= 70 ? "conf-high" : conf >= 45 ? "conf-mid" : "conf-low");
    meta.appendChild(confPill);

    const cited = (q.sources || []).filter((s) => s.cited_sentences).length;
    if (cited) meta.appendChild(el("span", "pill", `${cited} cited`));
    if (q.latency_ms) meta.appendChild(el("span", "pill", `${(q.latency_ms / 1000).toFixed(1)}s`));

    (q.notes || []).forEach((n) => {
      const label = {
        single_source: "single source",
        partial_coverage: "partial coverage",
        snippets_only: "snippets only",
        search_unavailable: "search unavailable",
        no_documents: "nothing readable",
      }[n] || n.replace(/_/g, " ");
      meta.appendChild(el("span", "pill warn", label));
    });

    card.appendChild(meta);

    // sources
    if (q.sources && q.sources.length) {
      const wrap = el("div", "sources");
      const head = el("div", "sources-head", `Sources · ${q.sources.length}`);
      wrap.appendChild(head);

      const list = el("div", "source-list");
      for (const s of q.sources) {
        const a = el("a", "source");
        a.href = s.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        if (s.cited_sentences) a.classList.add("is-cited");

        const num = el("span", "source-num", String(s.rank + 1));
        const bodyEl = el("div", "source-body");
        bodyEl.appendChild(el("div", "source-title", s.title || s.url));

        const dom = el("div", "source-domain");
        dom.appendChild(document.createTextNode(s.domain || domainOf(s.url)));
        if (!s.fetched) {
          const badge = el("span", "source-unread", "not read");
          badge.title = "This page couldn't be downloaded, so it isn't quoted.";
          dom.appendChild(badge);
        }
        bodyEl.appendChild(dom);

        a.append(num, bodyEl);
        list.appendChild(a);
      }
      wrap.appendChild(list);
      card.appendChild(wrap);
    }

    // follow-ups
    if (q.followups && q.followups.length) {
      const fu = el("div", "followups");
      fu.appendChild(el("div", "followups-head", "Keep going"));
      for (const f of q.followups) {
        const b = el("button", "followup");
        b.type = "button";
        b.appendChild(el("span", "fu-arrow", "→"));
        b.appendChild(el("span", null, f));
        b.addEventListener("click", () => {
          $("#question").value = f;
          autoGrow();
          ask(f);
        });
        fu.appendChild(b);
      }
      card.appendChild(fu);
    }

    return card;
  }

  // ── asking ──────────────────────────────────────────────────

  const STEPS = [
    "Searching the web…",
    "Reading the pages…",
    "Ranking sentences…",
    "Composing the answer…",
  ];

  function renderLoading() {
    const wrap = el("div", "turn");
    const qRow = el("div", "turn-q");
    qRow.append(
      el("div", "q-avatar", initials(state.user?.display_name || state.user?.email)),
      el("div", "q-text", $("#question").value.trim())
    );
    wrap.appendChild(qRow);

    const box = el("div", "loading");
    box.appendChild(el("div", "spinner"));
    const steps = el("div", "loading-steps");
    STEPS.forEach((s, i) => {
      const line = el("div", "loading-step", s);
      if (i === 0) line.classList.add("is-active");
      steps.appendChild(line);
    });
    box.appendChild(steps);
    wrap.appendChild(box);

    return { wrap, steps };
  }

  async function ask(question) {
    const q = (question || $("#question").value || "").trim();
    if (!q || state.busy) return;
    if (q.length < 3) {
      toast("Ask a slightly longer question.");
      return;
    }

    state.busy = true;
    $("#send-btn").disabled = true;
    $("#hero").hidden = true;

    const conv = $("#conversation");
    conv.hidden = false;

    const { wrap, steps } = renderLoading();
    conv.appendChild(wrap);
    scrollToBottom();

    // Advance the step labels on a timer. They're honest about the phases
    // the server actually runs, not fake progress.
    let stepIdx = 0;
    const ticker = setInterval(() => {
      if (stepIdx < steps.children.length - 1) {
        steps.children[stepIdx].classList.remove("is-active");
        steps.children[stepIdx].classList.add("is-done");
        stepIdx += 1;
        steps.children[stepIdx].classList.add("is-active");
      }
    }, 1400);

    try {
      const out = await api("/ask", {
        method: "POST",
        body: JSON.stringify({ question: q, thread_id: state.threadId }),
      });

      clearInterval(ticker);
      wrap.remove();

      state.threadId = out.thread.id;
      $("#topbar-title").textContent = out.thread.title || "Search";
      conv.appendChild(renderTurn(out.query));

      $("#question").value = "";
      autoGrow();

      await loadThreads();
      scrollToBottom();
    } catch (err) {
      clearInterval(ticker);
      wrap.remove();

      const errBox = el("div", "turn");
      const qRow = el("div", "turn-q");
      qRow.append(
        el("div", "q-avatar", initials(state.user?.display_name || state.user?.email)),
        el("div", "q-text", q)
      );
      errBox.appendChild(qRow);
      const box = el("div", "answer-error");
      box.textContent = err.message || "Something went wrong. Try again.";
      errBox.appendChild(box);
      conv.appendChild(errBox);
      scrollToBottom();
    } finally {
      state.busy = false;
      $("#send-btn").disabled = false;
      $("#question").focus();
    }
  }

  // ── layout helpers ──────────────────────────────────────────

  function scrollToBottom() {
    const s = $("#scroll");
    requestAnimationFrame(() => {
      s.scrollTop = s.scrollHeight;
    });
  }

  function autoGrow() {
    const ta = $("#question");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }

  function openSidebar() {
    $("#sidebar").classList.add("is-open");
    $("#scrim").hidden = false;
  }

  function closeSidebar() {
    $("#sidebar").classList.remove("is-open");
    $("#scrim").hidden = true;
  }

  // ── wiring ──────────────────────────────────────────────────

  function init() {
    document.querySelectorAll(".auth-tab").forEach((b) => {
      b.addEventListener("click", () => setAuthMode(b.dataset.mode));
    });
    $("#auth-form").addEventListener("submit", submitAuth);

    $("#demo-btn").addEventListener("click", () => {
      setAuthMode("login");
      const f = $("#auth-form");
      f.email.value = "demo@jawab.app";
      f.password.value = "demo12345";
      f.requestSubmit();
    });

    $("#logout-btn").addEventListener("click", () => signOut(false));
    $("#new-thread").addEventListener("click", newThread);
    $("#menu-btn").addEventListener("click", openSidebar);
    $("#scrim").addEventListener("click", closeSidebar);

    $("#composer").addEventListener("submit", (e) => {
      e.preventDefault();
      ask();
    });

    const ta = $("#question");
    ta.addEventListener("input", autoGrow);
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        ask();
      }
    });

    document.querySelectorAll(".suggestion").forEach((b) => {
      b.addEventListener("click", () => {
        $("#question").value = b.dataset.q;
        autoGrow();
        ask(b.dataset.q);
      });
    });

    if (state.token && state.user) {
      enterApp();
    } else {
      setAuthMode("login");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
