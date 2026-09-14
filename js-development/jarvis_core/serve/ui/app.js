/* JARVIS Body: a local chat surface. Transcript truth stays in the hearth. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const icons = {
    close: "m6 6 12 12M6 18 18 6",
    activity: "M2 12h4l3-8 6 16 3-8h4",
    diagonal: "M6 18 18 6M6 6h12v12",
    pause: "M8 5v14M16 5v14",
    play: "m8 5 11 7-11 7Z",
    eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    plus: "M12 5v14M5 12h14",
    search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M18 18A8 8 0 0 1 5 15",
    chevron: "m9 5 7 7-7 7",
    settings:
      "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z",
    menu: "M4 6h16M4 12h16M4 18h16",
    download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
    panel: "M3 4h18v16H3ZM15 4v16",
    layers: "m12 3 10 5-10 5L2 8ZM2 12l10 5 10-5M2 16l10 5 10-5",
    spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z",
    compass: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Zm-6-4-3 5-5 3 3-5Z",
    sliders: "M4 7h7m4 0h5M4 17h3m4 0h9M11 4v6M7 14v6",
    arrow: "M12 19V5m-6 6 6-6 6 6",
    chat: "M4 4h16v12H9l-5 4Z",
  };
  const svg = (name) =>
    `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.chat}"/></svg>`;
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = svg(el.dataset.icon);
  });
  const welcome = $("welcome").cloneNode(true);
  const filePreview = location.protocol === "file:";
  const remoteSurface = !["127.0.0.1", "localhost", "::1"].includes(location.hostname);
  $("connection-label").textContent = filePreview ? "DESIGN PREVIEW" : remoteSurface ? "SECURE REMOTE" : "PRIVATE LOCAL";
  const state = {
    sessions: [],
    messages: [],
    session: null,
    busy: false,
    loading: 0,
    trace: [],
    token: "",
    health: null,
  };
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const readLocal = (key, fallback = "") => {
    try {
      return localStorage.getItem(key) || fallback;
    } catch {
      return fallback;
    }
  };
  const writeLocal = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {}
  };
  let toastTimer;
  function toast(text) {
    $("toast").textContent = text;
    $("toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      $("toast").hidden = true;
    }, 3500);
  }
  function notice(text = "") {
    $("notice").textContent = text;
    $("notice").hidden = !text;
  }
  function authHeaders(extra = {}) {
    return { ...extra, Authorization: `Bearer ${state.token}` };
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: authHeaders(options.headers),
      signal: options.signal || AbortSignal.timeout(15000),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        response.status === 403
          ? "Connection token is missing or invalid. Open connection settings to reconnect."
          : data.error || `Request failed (${response.status}).`,
      );
    return data;
  }
  function formatTime(ts) {
    const date = new Date(ts);
    return Number.isNaN(+date)
      ? ""
      : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function age(seconds) {
    if (seconds == null) return "Not run yet";
    if (seconds < 60) return "Just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  }
  function setSidebar(open) {
    const wasOpen = $("sidebar").classList.contains("open");
    const narrow = innerWidth <= 760;
    $("sidebar").classList.toggle("open", open);
    $("scrim").hidden = !open;
    $("menu").setAttribute("aria-expanded", String(open));
    $("sidebar").inert = narrow && !open;
    document.querySelector(".main").inert = narrow && open;
    if (narrow && open) $("new-chat").focus();
    else if (narrow && wasOpen) $("menu").focus();
  }
  function toggleInspector(force) {
    const panel = $("inspector");
    const visible = !panel.hidden && getComputedStyle(panel).display !== "none";
    const show = force ?? !visible;
    panel.hidden = !show;
    panel.classList.toggle("open", show);
    $("inspector-button").setAttribute("aria-expanded", String(show));
  }
  function syncCore() {
    window.JarvisCore?.setBusy(state.busy || Boolean(state.health?.busy));
    if ($("core-caption")) $("core-caption").textContent = filePreview ? "Design preview · connect on the live app" : state.busy ? "Thinking with you" : state.health ? "Online. Ready when you are." : "Awaiting connection";
    const button = $("motion-toggle");
    if (button) {
      const paused = window.JarvisCore?.paused;
      button.setAttribute("aria-pressed", String(Boolean(paused)));
      button.setAttribute("aria-label", paused ? "Play core animation" : "Pause core animation");
      button.title = button.getAttribute("aria-label");
      button.innerHTML = svg(paused ? "play" : "pause");
    }
  }
  async function checkHealth() {
    if (!state.token || state.checkingHealth) return;
    state.checkingHealth = true;
    const started = performance.now();
    try {
      const h = await api("/v1/health");
      const degraded = h.ok === false || (h.jobs || []).some(job => /^(error|fail)/i.test(job.status || ""));
      state.health = h;
      document.body.dataset.connection = degraded ? "degraded" : "online";
      document.dispatchEvent(new CustomEvent("jarvis:health", { detail: { health: h, degraded, latency: Math.round(performance.now() - started) } }));
      syncCore();
      $("status-light").className =
        `status-light ${degraded ? "degraded" : h.busy ? "busy" : "online"}`;
      $("status-text").textContent = h.busy
        ? "JARVIS is thinking"
        : degraded ? "Background job needs attention" : "System online";
      $("pulse-state").textContent = degraded ? "Online · needs attention" : h.busy ? "Thinking in progress" : "System online";
      $("uptime").textContent =
        `${Math.floor(h.uptime_seconds / 3600)}h ${Math.floor(h.uptime_seconds / 60) % 60}m uptime`;
      $("metric-requests").textContent = h.requests_served;
      const names = {
        consolidate: "Memory consolidation",
        refresh_profile: "Cognitive profile",
        reindex_memory: "Memory index",
        ingest_codex: "Conversation capture",
        reconcile_codex_memory: "Memory reconciliation",
        refresh_digest: "Activity digest",
        rebuild_graphrag: "Graph memory",
      };
      $("jobs").replaceChildren();
      for (const job of h.jobs || []) {
        const row = document.createElement("div");
        row.className = `job ${/^(error|fail)/i.test(job.status || "") ? "error" : ""}`;
        row.innerHTML = `<span class="job-dot"></span><div><strong>${escape(names[job.name] || job.name.replaceAll("_", " "))}</strong><small>${escape(job.status || "Waiting")} · ${age(job.last_run_age_s)}</small></div>`;
        $("jobs").append(row);
      }
    } catch (error) {
      document.dispatchEvent(new CustomEvent("jarvis:health", { detail: { health: null } }));
      document.body.dataset.connection = "offline";
      // An ask can be actively running while a short status probe is delayed.
      // Do not overwrite the truthful in-flight state with a false disconnect.
      if (state.busy) {
        $("status-light").className = "status-light busy";
        $("status-text").textContent = "Response pending · status unavailable";
        $("pulse-state").textContent = "Health check unavailable";
        return;
      }
      state.health = null;
      $("status-light").className = "status-light";
      $("status-text").textContent = "Hearth disconnected";
      $("pulse-state").textContent = "Connection unavailable";
      $("uptime").textContent = "—";
      $("jobs").textContent = "Live status unavailable. Reconnect to refresh.";
      state.health = null;
      document.body.dataset.connection = "offline";
      syncCore();
    } finally {
      state.checkingHealth = false;
    }
  }
  async function loadSessions() {
    if (!state.token) return;
    const data = await api("/v1/sessions");
    state.sessions = data.sessions || [];
    renderSessions();
    $("metric-sessions").textContent = state.sessions.length;
  }
  function renderSessions() {
    const query = $("search").value.toLowerCase().trim();
    $("clear-search").hidden = !query;
    $("search-shortcut").hidden = Boolean(query);
    const sessions = state.sessions
      .filter((s) =>
        `${s.title} ${s.first_prompt} ${s.session_id}`
          .toLowerCase()
          .includes(query),
      )
      .sort((a, b) => {
        const aTime = Date.parse(a.latest_ts) || a.mtime * 1000 || 0;
        const bTime = Date.parse(b.latest_ts) || b.mtime * 1000 || 0;
        return bTime - aTime || b.session_id.localeCompare(a.session_id);
      });
    $("session-count").textContent = state.sessions.length;
    $("sessions").replaceChildren();
    let lastGroup = "";
    for (const session of sessions) {
      const date = new Date(session.latest_ts || session.mtime * 1000);
      const group =
        date.toDateString() === new Date().toDateString()
          ? "TODAY"
          : date
              .toLocaleDateString([], { month: "long", day: "numeric" })
              .toUpperCase();
      if (group !== lastGroup) {
        const label = document.createElement("div");
        label.className = "session-group";
        label.textContent = group;
        $("sessions").append(label);
        lastGroup = group;
      }
      const button = document.createElement("button");
      button.className = `session ${session.session_id === state.session ? "active" : ""}`;
      button.title = session.first_prompt || session.title;
      button.setAttribute(
        "aria-current",
        String(session.session_id === state.session),
      );
      button.innerHTML = `${svg("chat")}<span class="session-body"><span class="session-title">${escape(session.title || "Untitled conversation")}</span><span class="session-date">${session.turn_count} messages · ${formatTime(date)}</span></span>`;
      button.addEventListener("click", () => openSession(session.session_id));
      $("sessions").append(button);
    }
    if (!sessions.length) {
      const empty = document.createElement("p");
      empty.className = "muted empty-list";
      empty.textContent = query
        ? "No matching conversations."
        : "Your first conversation starts here.";
      $("sessions").append(empty);
    }
  }
  function rememberSession(id) {
    state.session = id;
    const url = new URL(location.href);
    if (id) url.searchParams.set("session", id);
    else url.searchParams.delete("session");
    history.replaceState({}, "", url);
  }
  function draftKey() {
    return `jarvis.draft.${state.session || "new"}`;
  }
  function resizePrompt() {
    $("prompt").style.height = "auto";
    $("prompt").style.height = `${Math.min($("prompt").scrollHeight, 200)}px`;
  }
  function restoreDraft() {
    $("prompt").value = readLocal(draftKey());
    resizePrompt();
  }
  function scrollBottom() {
    $("messages").scrollTop = $("messages").scrollHeight;
    $("jump-bottom").hidden = true;
  }
  async function openSession(id) {
    if (state.busy)
      return toast("Let this response finish before switching conversations.");
    const revision = ++state.loading;
    notice();
    setSidebar(false);
    try {
      const data = await api(`/v1/sessions/${encodeURIComponent(id)}`);
      if (revision !== state.loading) return;
      rememberSession(id);
      state.messages = data.messages || [];
      $("chat-title").textContent =
        state.sessions.find((s) => s.session_id === id)?.title ||
        "Conversation";
      document.title = `${$("chat-title").textContent} | JARVIS`;
      $("messages").replaceChildren();
      state.messages.forEach(renderMessage);
      if (!state.messages.length)
        $("messages").textContent =
          "This conversation has no saved messages yet.";
      restoreDraft();
      renderSessions();
      scrollBottom();
    } catch (error) {
      if (revision === state.loading) notice(error.message);
    }
  }
  function newSession() {
    if (state.busy)
      return toast(
        "Let this response finish before starting a new conversation.",
      );
    ++state.loading;
    rememberSession(null);
    state.messages = [];
    state.trace = [];
    $("chat-title").textContent = "New conversation";
    document.title = "JARVIS | Personal intelligence";
    $("messages").replaceChildren(welcome.cloneNode(true));
    window.JarvisCore?.setScroll(0);
    syncCore();
    notice();
    restoreDraft();
    renderSessions();
    setSidebar(false);
    $("prompt").focus();
  }
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied in full");
    } catch {
      toast("Clipboard unavailable. Use Export or select the message text.");
    }
  }

  // Raw HTML is displayed literally. Only a small set of generated Markdown tags survives.
  if (window.marked)
    marked.use({
      renderer: {
        html: (token) => escape(token.text),
        image: (token) => escape(`[Image: ${token.text || "image"}]`),
      },
    });
  function renderMarkdown(container, source) {
    if (!window.marked) {
      container.textContent = source;
      container.classList.add("raw");
      return;
    }
    const template = document.createElement("template");
    template.innerHTML = marked.parse(source, { gfm: true, breaks: false });
    const allowed = new Set(
      "P BR STRONG EM DEL S BLOCKQUOTE UL OL LI H1 H2 H3 H4 H5 H6 PRE CODE HR TABLE THEAD TBODY TR TH TD A INPUT".split(
        " ",
      ),
    );
    for (const el of [...template.content.querySelectorAll("*")]) {
      if (!allowed.has(el.tagName)) {
        el.replaceWith(document.createTextNode(el.textContent));
        continue;
      }
      const href = el.getAttribute("href"),
        language = el.className,
        start = el.getAttribute("start");
      const checked = el.hasAttribute("checked");
      for (const attr of [...el.attributes]) el.removeAttribute(attr.name);
      if (el.tagName === "A" && href) {
        try {
          const url = new URL(href, location.origin);
          if (["http:", "https:", "mailto:"].includes(url.protocol)) {
            el.href = url.href;
            el.target = "_blank";
            el.rel = "noopener noreferrer";
          }
        } catch {}
      }
      if (el.tagName === "CODE" && /^language-[\w+-]+$/.test(language))
        el.className = language;
      if (el.tagName === "OL" && /^\d+$/.test(start || ""))
        el.start = Number(start);
      if (el.tagName === "INPUT") {
        el.type = "checkbox";
        el.disabled = true;
        el.checked = checked;
      }
    }
    container.replaceChildren(template.content);
    for (const pre of container.querySelectorAll("pre")) {
      const code = pre.querySelector("code");
      const raw = code?.textContent || pre.textContent;
      const label = document.createElement("span");
      label.className = "code-language";
      label.textContent = code?.className.replace("language-", "") || "code";
      const button = document.createElement("button");
      button.textContent = "Copy code";
      button.onclick = () => copy(raw);
      pre.prepend(label, button);
    }
    for (const table of container.querySelectorAll("table")) {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      table.replaceWith(wrap);
      wrap.append(table);
    }
  }
  function renderMessage(message) {
    const row = document.createElement("article");
    const isUser = message.role === "user";
    row.className = `message ${isUser ? "user" : "assistant"}`;
    const heading = document.createElement("div");
    heading.className = "message-heading";
    heading.innerHTML = `<span class="message-avatar">${isUser ? "SN" : "J"}</span><span>${isUser ? "YOU" : "JARVIS"}</span><time>${formatTime(message.ts)}</time><span class="message-actions"></span>`;
    const body = document.createElement("div");
    body.className = "message-content";
    const source = String(message.content ?? "");
    if (isUser) body.textContent = source;
    else renderMarkdown(body, source);
    const copyButton = document.createElement("button");
    copyButton.textContent = "Copy";
    copyButton.setAttribute(
      "aria-label",
      `Copy full ${isUser ? "message" : "answer"}`,
    );
    copyButton.onclick = () => copy(source);
    heading.lastElementChild.append(copyButton);
    if (!isUser) {
      const raw = document.createElement("button");
      raw.textContent = "Raw";
      raw.onclick = () => {
        const showRaw = !body.classList.contains("raw");
        body.classList.toggle("raw", showRaw);
        if (showRaw) body.textContent = source;
        else renderMarkdown(body, source);
        raw.textContent = showRaw ? "Formatted" : "Raw";
      };
      heading.lastElementChild.append(raw);
      if ("speechSynthesis" in window) {
        const listen = document.createElement("button");
        listen.textContent = "Listen";
        listen.setAttribute("aria-label", "Read answer aloud with browser voice");
        listen.onclick = () => document.dispatchEvent(new CustomEvent("jarvis:speak", { detail: { text: body.innerText } }));
        heading.lastElementChild.append(listen);
      }
    }
    row.append(heading, body);
    if (message.telemetry) {
      const t = message.telemetry,
        meta = document.createElement("div");
      meta.className = "message-meta";
      const entries = [
        t.ledger?.model,
        t.verdict,
        Number.isFinite(t.confidence)
          ? `${Math.round(t.confidence * 100)}% confidence`
          : null,
        Number.isFinite(t.ledger?.spend_usd)
          ? `$${t.ledger.spend_usd.toFixed(4)}`
          : null,
      ];
      for (const text of entries.filter(Boolean)) {
        const span = document.createElement("span");
        span.textContent = text;
        if (text === "ESCALATE") span.className = "escalate";
        meta.append(span);
      }
      row.append(meta);
    }
    $("messages").append(row);
    return row;
  }
  // Event names and UTF-8 decoder state must outlive individual network chunks.
  async function consumeEvents(response, onEvent) {
    if (!response.body)
      throw new Error("This browser cannot read the response stream.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "",
      event = "message",
      data = [];
    const dispatch = () => {
      if (data.length) onEvent(event, JSON.parse(data.join("\n")));
      event = "message";
      data = [];
    };
    const line = (value) => {
      const s = value.replace(/\r$/, "");
      if (!s) {
        dispatch();
        return;
      }
      if (s.startsWith(":")) return;
      const split = s.indexOf(":");
      const key = split < 0 ? s : s.slice(0, split);
      let valuePart = split < 0 ? "" : s.slice(split + 1);
      if (valuePart.startsWith(" ")) valuePart = valuePart.slice(1);
      if (key === "event") event = valuePart;
      if (key === "data") data.push(valuePart);
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += done
          ? decoder.decode()
          : decoder.decode(value, { stream: true });
        let end;
        while ((end = buffer.indexOf("\n")) >= 0) {
          line(buffer.slice(0, end));
          buffer = buffer.slice(end + 1);
        }
        if (done) break;
      }
      if (buffer) line(buffer);
      dispatch();
    } finally {
      reader.releaseLock();
    }
  }
  function setBusy(busy) {
    state.busy = busy;
    document.body.dataset.busy = String(busy);
    window.JarvisCore?.setBusy(busy);
    syncCore();
    $("send").disabled = busy;
    $("working").hidden = !busy;
    $("messages").setAttribute("aria-busy", String(busy));
  }
  async function submit(event) {
    event.preventDefault();
    const question = $("prompt").value.trim();
    if (!question || state.busy) return;
    if (filePreview) { notice("This is a design preview. Open http://127.0.0.1:8756/ to talk to your local JARVIS."); return; }
    if (!state.token) {
      $("settings").showModal();
      return;
    }
    ++state.loading;
    notice();
    const oldDraftKey = draftKey();
    if (!state.session) rememberSession(`conv-web-${crypto.randomUUID()}`);
    const session = state.session;
    const request = {
      question,
      session,
      full: $("tools").value === "full",
      allow_all: $("allow-all").checked,
    };
    if ($("model").value.trim()) request.model = $("model").value.trim();
    if ($("reasoning").value) request.reasoning_effort = $("reasoning").value;
    $("welcome")?.remove();
    const user = {
      role: "user",
      content: question,
      ts: new Date().toISOString(),
    };
    state.messages.push(user);
    renderMessage(user);
    $("chat-title").textContent =
      state.sessions.find((s) => s.session_id === session)?.title || question;
    document.title = `${$("chat-title").textContent} | JARVIS`;
    $("prompt").value = "";
    writeLocal(oldDraftKey, "");
    writeLocal(draftKey(), "");
    resizePrompt();
    setBusy(true);
    scrollBottom();
    state.trace = [];
    $("trace").textContent = "";
    $("trace-count").textContent = "0";
    $("working-text").textContent = "JARVIS is thinking";
    const started = Date.now();
    const timer = setInterval(() => {
      $("elapsed").textContent =
        `${Math.floor((Date.now() - started) / 1000)}s`;
    }, 1000);
    let final = null;
    try {
      const response = await fetch("/v1/ask", {
        method: "POST",
        headers: authHeaders({
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        }),
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.error || `Request failed (${response.status})`);
      }
      await consumeEvents(response, (type, data) => {
        if (type === "answer") final = data;
        if (type === "log") {
          const text = String(data.line || "");
          state.trace.push(text);
          $("trace").append(document.createTextNode(text + "\n"));
          $("trace-count").textContent = state.trace.length;
          const brain = text.match(/^\s*brain\s*:\s*(.+)/);
          if (brain) $("working-text").textContent = `Thinking · ${brain[1]}`;
          if (/^\s*(tool|\[tool)/i.test(text))
            $("working-text").textContent = "JARVIS is using tools";
        }
      });
      if (!final)
        throw new Error(
          "The connection ended before a final answer arrived. Refresh this conversation to check whether it was saved.",
        );
      if (!final.ok)
        throw new Error(
          final.error || "JARVIS could not complete this request.",
        );
      const answer = {
        role: "assistant",
        content: String(final.answer || ""),
        ts: new Date().toISOString(),
        telemetry: final,
      };
      state.messages.push(answer);
      renderMessage(answer);
      if (final.denials?.length)
        notice(
          `Some tools require approval: ${final.denials.map((d) => (typeof d === "string" ? d : d.tool)).join(", ")}. See Configure before your next request.`,
        );
      // Verify durability, not just a successful stream. Provider-error or degenerate answers may be intentionally unsaved.
      if (final.persisted !== false && !final.degenerate) {
        try {
          const saved = await api(`/v1/sessions/${encodeURIComponent(session)}`);
          const last = [...(saved.messages || [])]
            .reverse()
            .find((m) => m.role === "assistant");
          if (last?.content !== answer.content)
            notice(
              "This response is visible here but was not saved in full by the hearth. Export it before leaving this chat.",
            );
        } catch {
          notice(
            "This response is visible here, but saved history could not be verified. Export it before leaving this chat.",
          );
        }
      }
    } catch (error) {
      notice(error.message);
      $("prompt").value = question;
      writeLocal(draftKey(), question);
      resizePrompt();
    } finally {
      clearInterval(timer);
      setBusy(false);
      $("elapsed").textContent = "0s";
      scrollBottom();
      await checkHealth();
      try {
        await loadSessions();
      } catch (error) {
        notice(error.message);
      }
    }
  }
  async function connect(event) {
    event?.preventDefault();
    const candidate = $("token").value.trim();
    if (!candidate) {
      $("token").setAttribute("aria-invalid", "true");
      $("connection-error").textContent =
        "Choose the local token file or enter its contents.";
      return;
    }
    const previous = state.token;
    state.token = candidate;
    const button = $("connection-form").querySelector('[type="submit"]');
    button.disabled = true;
    $("connection-error").textContent = "Connecting…";
    $("token").removeAttribute("aria-invalid");
    try {
      await api("/v1/auth/verify");
      try {
        sessionStorage.setItem("jarvis_hearth_token", candidate);
        localStorage.removeItem("jarvis_hearth_token");
      } catch {}
      $("token").value = "";
      $("token").type = "password";
      $("show-token").setAttribute("aria-label", "Show token");
      $("connection-error").textContent = "";
      $("settings").close();
      await checkHealth();
      await loadSessions();
      const id = new URL(location.href).searchParams.get("session");
      if (id) await openSession(id);
    } catch (error) {
      state.token = previous;
      $("connection-error").textContent = error.message;
      $("token").setAttribute("aria-invalid", "true");
    } finally {
      button.disabled = false;
    }
  }
  $("composer").onsubmit = submit;
  $("prompt").oninput = () => {
    resizePrompt();
    writeLocal(draftKey(), $("prompt").value);
  };
  $("prompt").onkeydown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  };
  $("search").oninput = renderSessions;
  $("clear-search").onclick = () => { $("search").value = ""; renderSessions(); $("search").focus(); };
  $("refresh").onclick = async () => {
    try {
      await loadSessions();
      if (state.session && !state.busy) await openSession(state.session);
      toast("History refreshed");
    } catch (error) {
      notice(error.message);
    }
  };
  $("new-chat").onclick = newSession;
  document.querySelector(".brand").onclick = (event) => {
    event.preventDefault();
    newSession();
  };
  $("messages").onclick = (event) => {
    if (event.target.closest("#motion-toggle")) { window.JarvisCore?.togglePause(); syncCore(); return; }
    const button = event.target.closest("[data-prompt]");
    if (button) {
      $("prompt").value = button.dataset.prompt;
      resizePrompt();
      writeLocal(draftKey(), $("prompt").value);
      $("prompt").focus();
    }
  };
  $("messages").onscroll = () => {
    window.JarvisCore?.setScroll($("messages").scrollTop / Math.max(1, $("messages").scrollHeight - $("messages").clientHeight));
    $("jump-bottom").hidden =
      $("messages").scrollHeight -
        $("messages").scrollTop -
        $("messages").clientHeight <
      180;
  };
  $("jump-bottom").onclick = scrollBottom;
  $("menu").onclick = () =>
    setSidebar(!$("sidebar").classList.contains("open"));
  $("scrim").onclick = () => setSidebar(false);
  $("inspector-button").onclick = () => toggleInspector();
  $("system-toggle").onclick = () => { setSidebar(false); toggleInspector(); };
  $("close-inspector").onclick = () => toggleInspector(false);
  $("options-button").onclick = () => {
    $("options").hidden = !$("options").hidden;
    $("options-button").setAttribute(
      "aria-expanded",
      String(!$("options").hidden),
    );
  };
  $("settings-button").onclick = () => $("settings").showModal();
  $("close-settings").onclick = () => $("settings").close();
  $("connection-form").onsubmit = connect;
  $("show-token").onclick = () => {
    const show = $("token").type === "password";
    $("token").type = show ? "text" : "password";
    $("show-token").setAttribute("aria-label", show ? "Hide token" : "Show token");
  };
  $("token-file").onchange = async (event) => {
    const file = event.target.files[0];
    if (file) {
      if (file.size > 2048) {
        $("connection-error").textContent =
          "Choose the small .hearth_token file.";
        return;
      }
      $("token").value = (await file.text()).trim();
    }
  };
  $("export").onclick = () => {
    if (!state.messages.length)
      return toast("Open a conversation to export it.");
    const text = state.messages
      .map(
        (m) =>
          `## ${m.role === "user" ? "You" : "JARVIS"}${m.ts ? " · " + m.ts : ""}\n\n${m.content}`,
      )
      .join("\n\n---\n\n");
    const url = URL.createObjectURL(
      new Blob([text], { type: "text/markdown;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${state.session || "jarvis-conversation"}.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  // Model and reasoning are deliberate working preferences. Preserve them
  // across browser reloads so a serious conversation does not silently fall
  // back to a weaker configuration.  Gated tools remain opt-in per request:
  // persistence must never turn a later conversational turn into an action.
  for (const id of ["model", "reasoning"]) {
    $(id).value = readLocal(`jarvis.${id}`, $(id).value);
    $(id).onchange = () => writeLocal(`jarvis.${id}`, $(id).value);
  }
  $("tools").value = "default";
  document.onkeydown = (event) => {
    if (event.key === "Tab" && innerWidth <= 760 && $("sidebar").classList.contains("open")) {
      const controls = [...$("sidebar").querySelectorAll('a,button,input')].filter(el => !el.hidden && el.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if (event.key === "/" && !typing && !$("settings").open) {
      event.preventDefault();
      if (innerWidth <= 760) setSidebar(true);
      $("search").focus();
    }
    if (event.altKey && event.key.toLowerCase() === "n") {
      event.preventDefault();
      newSession();
    }
    if (event.key === "Escape") setSidebar(false);
  };
  async function boot() {
    syncCore();
    if (filePreview) {
      $("status-text").textContent = "Design preview";
      notice("Design preview only. Open http://127.0.0.1:8756/ to connect to your local hearth and conversations.");
      return;
    }
    const url = new URL(location.href);
    const fragment = new URLSearchParams(url.hash.slice(1));
    const supplied = fragment.get("token") || url.searchParams.get("token");
    try {
      state.token =
        supplied ||
        sessionStorage.getItem("jarvis_hearth_token") ||
        localStorage.getItem("jarvis_hearth_token") ||
        "";
      if (state.token)
        sessionStorage.setItem("jarvis_hearth_token", state.token);
      localStorage.removeItem("jarvis_hearth_token");
    } catch {
      state.token = supplied || "";
    }
    if (supplied) {
      url.searchParams.delete("token");
      url.hash = "";
      history.replaceState({}, "", url);
    }
    restoreDraft();
    if (!state.token) {
      $("settings").showModal();
      return;
    }
    await checkHealth();
    try {
      await loadSessions();
      const id = url.searchParams.get("session");
      if (id) await openSession(id);
    } catch (error) {
      notice(error.message);
    }
  }
  boot();
  setSidebar(false);
  addEventListener("resize", () => { if (innerWidth > 760) setSidebar(false); else $("sidebar").inert = !$("sidebar").classList.contains("open"); });
  document.addEventListener("jarvis:motionchange", syncCore);
  setInterval(() => {
    if (!document.hidden) checkHealth();
  }, 5000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkHealth(); });
})();
