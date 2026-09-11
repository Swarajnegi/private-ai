/**
 * JARVIS Web Dashboard Client
 * Zero-dependency ES6 application connecting to Hearth ASGI server.
 */

(function () {
  // DOM Elements
  const sessionListEl = document.getElementById('session-list');
  const sessionCountEl = document.getElementById('session-count');
  const sessionTagEl = document.getElementById('session-tag');
  const sessionTitleDisplayEl = document.getElementById('session-title-display');
  const messagesStreamEl = document.getElementById('messages-stream');
  const promptInputEl = document.getElementById('prompt-input');
  const btnSubmitEl = document.getElementById('btn-submit');
  const btnNewChatEl = document.getElementById('btn-new-chat');
  const selectModelEl = document.getElementById('select-model');
  const reasoningTogglesEl = document.getElementById('reasoning-toggles');
  const toolModeTogglesEl = document.getElementById('tool-mode-toggles');
  const checkAllowAllEl = document.getElementById('check-allow-all');
  const activityDockEl = document.getElementById('activity-dock');
  const activityTraceEl = document.getElementById('activity-trace');
  const activityBadgeEl = document.getElementById('activity-badge');
  const activityLabelEl = document.getElementById('activity-label');
  const statusDotEl = document.getElementById('status-dot');
  const statusLabelEl = document.getElementById('status-label');
  const statusSubEl = document.getElementById('status-sub');
  const tokenStatusPillEl = document.getElementById('token-status-pill');
  const modalSettingsEl = document.getElementById('modal-settings');
  const btnSettingsEl = document.getElementById('btn-settings');
  const modalCloseEl = document.getElementById('modal-close');
  const inputTokenEl = document.getElementById('input-token');
  const btnSaveTokenEl = document.getElementById('btn-save-token');

  // App State
  let currentSessionId = null;
  let authToken = '';
  let activeReasoningEffort = 'high';
  let activeToolMode = 'full';
  let isGenerating = false;
  let activeTraceLines = [];

  // --- TOKEN INITIALIZATION ---
  function initAuthToken() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlToken = urlParams.get('token');
    if (urlToken) {
      authToken = urlToken.trim();
      localStorage.setItem('jarvis_hearth_token', authToken);
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      authToken = localStorage.getItem('jarvis_hearth_token') || '';
    }

    if (!authToken) {
      tokenStatusPillEl.className = 'pill';
      tokenStatusPillEl.textContent = 'Token Required';
      openSettingsModal();
    } else {
      tokenStatusPillEl.className = 'pill success';
      tokenStatusPillEl.textContent = 'Token Configured';
    }
  }

  function getAuthHeaders(customHeaders = {}) {
    const headers = { ...customHeaders };
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    return headers;
  }

  // --- HEARTH HEALTH CHECK ---
  async function checkHealth() {
    try {
      const res = await fetch('/v1/health', { headers: getAuthHeaders() });
      if (res.status === 200) {
        const data = await res.json();
        statusDotEl.className = 'status-indicator online' + (data.busy ? ' busy' : '');
        statusLabelEl.textContent = data.busy ? 'Hearth: Processing' : 'Hearth: Online';
        statusSubEl.textContent = `Port 8756 • PID ${data.pid} • ${Math.round(data.uptime_seconds)}s`;
      } else if (res.status === 403) {
        statusDotEl.className = 'status-indicator';
        statusLabelEl.textContent = 'Auth Required';
        statusSubEl.textContent = 'Token invalid or missing';
      }
    } catch (e) {
      statusDotEl.className = 'status-indicator';
      statusLabelEl.textContent = 'Hearth: Offline';
      statusSubEl.textContent = 'Connection refused';
    }
  }

  // --- SESSIONS LOADING ---
  async function loadSessions() {
    if (!authToken) return;
    try {
      const res = await fetch('/v1/sessions', { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        renderSessionList(data.sessions || []);
      }
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  }

  function renderSessionList(sessions) {
    sessionCountEl.textContent = sessions.length;
    if (sessions.length === 0) {
      sessionListEl.innerHTML = '<div class="session-loading">No past conversations</div>';
      return;
    }

    sessionListEl.innerHTML = '';
    sessions.forEach(sess => {
      const item = document.createElement('div');
      item.className = 'session-item' + (sess.session_id === currentSessionId ? ' active' : '');
      item.dataset.id = sess.session_id;

      const dateStr = sess.latest_ts ? sess.latest_ts.split('T')[0] : 'Past';

      item.innerHTML = `
        <div class="session-item-title" title="${escapeHtml(sess.first_prompt || sess.title)}">
          ${escapeHtml(sess.title || 'Untitled Session')}
        </div>
        <div class="session-item-meta">
          <span>${sess.turn_count} turns</span>
          <span>${dateStr}</span>
        </div>
      `;

      item.addEventListener('click', () => switchSession(sess.session_id, sess.title));
      sessionListEl.appendChild(item);
    });
  }

  async function switchSession(sessionId, title) {
    if (isGenerating) return;
    currentSessionId = sessionId;
    sessionTagEl.textContent = 'ACTIVE SESSION';
    sessionTitleDisplayEl.textContent = title || sessionId;

    // Highlight active in sidebar
    document.querySelectorAll('.session-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === sessionId);
    });

    // Fetch history
    try {
      messagesStreamEl.innerHTML = '<div class="session-loading">Loading session turns...</div>';
      const res = await fetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, {
        headers: getAuthHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        renderSessionHistory(data.messages || []);
      } else {
        messagesStreamEl.innerHTML = '<div class="hero-placeholder"><p>Could not load session.</p></div>';
      }
    } catch (e) {
      console.error('Error fetching session:', e);
      messagesStreamEl.innerHTML = '<div class="hero-placeholder"><p>Error connecting to Hearth.</p></div>';
    }
  }

  function renderSessionHistory(messages) {
    messagesStreamEl.innerHTML = '';
    if (messages.length === 0) {
      messagesStreamEl.innerHTML = '<div class="hero-placeholder"><p>Empty conversation record.</p></div>';
      return;
    }

    messages.forEach(msg => {
      appendMessageBubble(msg.role, msg.content, { ts: msg.ts });
    });
    scrollToBottom();
  }

  function startNewSession() {
    if (isGenerating) return;
    currentSessionId = null;
    sessionTagEl.textContent = 'NEW SESSION';
    sessionTitleDisplayEl.textContent = 'Interactive Operating Console';

    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));

    messagesStreamEl.innerHTML = `
      <div class="hero-placeholder" id="hero-placeholder">
        <div class="hero-icon">
          <div class="ring outer"></div>
          <div class="ring inner"></div>
          <div class="core-glow"></div>
        </div>
        <h2>JARVIS Autonomous Cognitive Orchestrator</h2>
        <p>Autonomous R&D, Memory Triangulation, and Systems Engineering.</p>
        <div class="quick-prompts">
          <button class="prompt-chip" data-prompt="have you gone through the entire local JARVIS folder? what do you think about this project? like what is it about and what is it I am building and trying to achieve with this in the long long term?">
            🏢 Audit repository architecture & long-term endgame
          </button>
          <button class="prompt-chip" data-prompt="What past JARVIS decisions constrain the task I am starting today?">
            🛡️ Check past authoritative decisions for Stage 5
          </button>
          <button class="prompt-chip" data-prompt="Check the current volume of our observation queue, knowledge base, and domain labels using your corpus introspection tool.">
            📊 Inspect observation queue & corpus volume
          </button>
        </div>
      </div>
    `;

    bindQuickPrompts();
    promptInputEl.focus();
  }

  // --- SENDING INQUIRIES & SSE STREAMING ---
  async function submitQuery() {
    const text = promptInputEl.value.trim();
    if (!text || isGenerating) return;

    if (!authToken) {
      openSettingsModal();
      return;
    }

    // Clear placeholder
    const heroEl = document.getElementById('hero-placeholder');
    if (heroEl) heroEl.remove();

    // Append user message
    appendMessageBubble('user', text);
    promptInputEl.value = '';
    adjustTextareaHeight();
    scrollToBottom();

    // Prepare Request Body
    const requestPayload = {
      question: text,
      model: selectModelEl.value,
      reasoning_effort: activeReasoningEffort,
      full: activeToolMode === 'full',
      allow_all: checkAllowAllEl.checked,
    };

    if (currentSessionId) {
      requestPayload.session = currentSessionId;
    } else {
      requestPayload.new_session = true;
    }

    // Start Generating State
    isGenerating = true;
    btnSubmitEl.disabled = true;
    activeTraceLines = [];
    activityTraceEl.innerHTML = '';
    activityBadgeEl.textContent = '0 steps';
    activityLabelEl.textContent = 'JARVIS is thinking & executing tools...';
    activityDockEl.classList.remove('hidden');

    const startTime = Date.now();

    try {
      const response = await fetch('/v1/ask', {
        method: 'POST',
        headers: getAuthHeaders({
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        }),
        body: JSON.stringify(requestPayload)
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: response.statusText }));
        activityDockEl.classList.add('hidden');
        appendMessageBubble('assistant', `⚠️ **Error ${response.status}:** ${err.error || 'Request failed'}`);
        isGenerating = false;
        btnSubmitEl.disabled = false;
        return;
      }

      // Stream SSE chunks
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let finalPayload = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep remainder

        let currentEvent = 'message';
        for (let line of lines) {
          line = line.trim();
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const rawData = line.slice(5).trim();
            try {
              const data = JSON.parse(rawData);
              if (currentEvent === 'log') {
                handleLogEvent(data);
              } else if (currentEvent === 'answer') {
                finalPayload = data;
              }
            } catch (e) {
              console.warn('Malformed SSE data frame:', rawData);
            }
          }
        }
      }

      const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);
      activityDockEl.classList.add('hidden');

      if (finalPayload) {
        appendMessageBubble('assistant', finalPayload.answer || '(No response text)', {
          telemetry: finalPayload,
          trace: activeTraceLines,
          duration: `${elapsedSec}s`
        });

        // Update session tracking
        if (!currentSessionId) {
          loadSessions();
        }
      } else {
        appendMessageBubble('assistant', '⚠️ Finished with no answer payload received.');
      }
    } catch (e) {
      console.error('Inference error:', e);
      activityDockEl.classList.add('hidden');
      appendMessageBubble('assistant', `⚠️ **Connection Error:** Could not reach Hearth daemon (${e.message}).`);
    } finally {
      isGenerating = false;
      btnSubmitEl.disabled = false;
      scrollToBottom();
      checkHealth();
    }
  }

  function handleLogEvent(data) {
    if (!data || !data.line) return;
    const line = String(data.line).trim();
    activeTraceLines.push(line);

    const row = document.createElement('div');
    row.className = 'trace-line';

    if (line.startsWith('tool')) {
      const parts = line.split('->');
      const toolCall = parts[0].trim();
      const rest = parts.slice(1).join('->').trim();
      row.innerHTML = `<span class="tool-tag">${escapeHtml(toolCall)}</span>: ${escapeHtml(rest.slice(0, 140))}`;
    } else {
      row.textContent = line.slice(0, 160);
    }

    activityTraceEl.appendChild(row);
    activityTraceEl.scrollTop = activityTraceEl.scrollHeight;
    activityBadgeEl.textContent = `${activeTraceLines.length} events`;
  }

  // --- MESSAGE BUBBLE RENDERING ---
  function appendMessageBubble(role, content, options = {}) {
    const row = document.createElement('div');
    row.className = `message-row ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    if (role === 'user') {
      bubble.textContent = content;
    } else {
      // Formatted assistant response
      let html = `<div class="markdown-body">${renderMarkdown(content)}</div>`;

      // Telemetry & Details Chip
      if (options.telemetry) {
        const t = options.telemetry;
        const spend = t.ledger && t.ledger.spend_usd ? `$${t.ledger.spend_usd.toFixed(4)}` : '$0.00';
        const model = (t.ledger && t.ledger.model) || selectModelEl.value;
        const conf = t.confidence ? Math.round(t.confidence * 100) : null;
        let confClass = 'high';
        if (t.confidence < 0.6) confClass = 'uncertain';
        else if (t.confidence < 0.8) confClass = 'medium';

        html += `
          <div class="message-telemetry">
            <span>⚡ ${escapeHtml(model)}</span>
            <span>⏱️ ${options.duration || ''}</span>
            <span>💰 ${spend}</span>
            ${conf !== null ? `<span class="telemetry-pill ${confClass}">Conf: ${conf}%</span>` : ''}
            ${options.trace && options.trace.length ? `<span>🛠️ ${options.trace.length} tool calls</span>` : ''}
          </div>
        `;
      }

      bubble.innerHTML = html;
    }

    row.appendChild(bubble);
    messagesStreamEl.appendChild(row);
    scrollToBottom();
  }

  // --- LIGHTWEIGHT SAFE MARKDOWN PARSER ---
  function renderMarkdown(md) {
    if (!md) return '';
    let text = escapeHtml(md);

    // Code blocks with syntax box
    text = text.replace(/```([a-zA-Z0-9_\-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
    });

    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers
    text = text.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    // Bold & Italics
    text = text.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/gim, '<em>$1</em>');

    // Blockquotes
    text = text.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');

    // Horizontal rules
    text = text.replace(/^---$/gim, '<hr>');

    // Lists
    text = text.replace(/^\s*[\-\*]\s+(.*$)/gim, '<ul><li>$1</li></ul>');
    text = text.replace(/<\/ul>\s*<ul>/gim, '');

    // Paragraphs & Line Breaks
    const paragraphs = text.split(/\n\n+/);
    text = paragraphs.map(p => {
      if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul>') || p.startsWith('<blockquote>') || p.startsWith('<hr>')) {
        return p;
      }
      return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');

    return text;
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function scrollToBottom() {
    messagesStreamEl.scrollTop = messagesStreamEl.scrollHeight;
  }

  function adjustTextareaHeight() {
    promptInputEl.style.height = 'auto';
    promptInputEl.style.height = Math.min(promptInputEl.scrollHeight, 180) + 'px';
  }

  // --- SETTINGS MODAL ---
  function openSettingsModal() {
    inputTokenEl.value = authToken;
    modalSettingsEl.classList.remove('hidden');
    inputTokenEl.focus();
  }

  function closeSettingsModal() {
    modalSettingsEl.classList.add('hidden');
  }

  function saveAuthToken() {
    const val = inputTokenEl.value.trim();
    if (val) {
      authToken = val;
      localStorage.setItem('jarvis_hearth_token', authToken);
      tokenStatusPillEl.className = 'pill success';
      tokenStatusPillEl.textContent = 'Token Configured';
      closeSettingsModal();
      checkHealth();
      loadSessions();
    }
  }

  // --- EVENT LISTENERS ---
  function bindEvents() {
    // Quick prompt chip clicks
    bindQuickPrompts();

    // Auto-resizing textarea & Keybindings
    promptInputEl.addEventListener('input', adjustTextareaHeight);
    promptInputEl.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitQuery();
      }
    });

    btnSubmitEl.addEventListener('click', submitQuery);
    btnNewChatEl.addEventListener('click', startNewSession);

    // Reasoning effort buttons
    reasoningTogglesEl.addEventListener('click', e => {
      const btn = e.target.closest('.toggle-btn');
      if (!btn) return;
      reasoningTogglesEl.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeReasoningEffort = btn.dataset.val;
    });

    // Tool mode buttons
    toolModeTogglesEl.addEventListener('click', e => {
      const btn = e.target.closest('.toggle-btn');
      if (!btn) return;
      toolModeTogglesEl.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeToolMode = btn.dataset.val;
    });

    // Settings Modal
    btnSettingsEl.addEventListener('click', openSettingsModal);
    modalCloseEl.addEventListener('click', closeSettingsModal);
    btnSaveTokenEl.addEventListener('click', saveAuthToken);
    modalSettingsEl.addEventListener('click', e => {
      if (e.target === modalSettingsEl) closeSettingsModal();
    });
  }

  function bindQuickPrompts() {
    document.querySelectorAll('.prompt-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const text = btn.dataset.prompt;
        if (text) {
          promptInputEl.value = text;
          adjustTextareaHeight();
          submitQuery();
        }
      });
    });
  }

  // --- INITIALIZATION ---
  initAuthToken();
  bindEvents();
  checkHealth();
  loadSessions();
  setInterval(checkHealth, 10000);
})();
