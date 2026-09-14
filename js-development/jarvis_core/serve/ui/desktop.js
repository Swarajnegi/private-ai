/* Body: accessible dark model picker, measured hearth pulse and optional speech.
 * No model calls or transcript writes; the existing app owns those contracts. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const select = $('model');
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'model-trigger';
  trigger.id = 'model-picker';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-controls', 'model-dialog');
  trigger.innerHTML = '<span class="model-name"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>';
  const dialog = document.createElement('dialog');
  dialog.id = 'model-dialog';
  dialog.className = 'model-dialog';
  dialog.setAttribute('aria-labelledby', 'model-title');
  dialog.innerHTML = '<div class="dialog-heading"><div><p class="eyebrow">CHOOSE YOUR INTELLIGENCE</p><h2 id="model-title">Models</h2></div><button class="icon-button" type="button" aria-label="Close model picker">✕</button></div><label class="sr-only" for="model-search">Search models</label><input id="model-search" class="model-search" type="search" placeholder="Search by model or provider…" autocomplete="off"><div class="model-list" aria-label="Available models"></div><p class="model-note">Paid models use your OpenRouter balance. Availability and pricing are set by the provider.</p>';
  document.body.append(dialog);
  const search = $('model-search'), list = dialog.querySelector('.model-list');
  const name = text => text.split(' · ')[0];
  function update() {
    const option = select.selectedOptions[0];
    trigger.querySelector('.model-name').textContent = option ? name(option.textContent) : 'Choose a model';
    trigger.setAttribute('aria-label', `Choose model: ${option ? name(option.textContent) : 'not selected'}`);
  }
  function render() {
    list.replaceChildren();
    const q = search.value.toLowerCase().trim();
    let count = 0;
    for (const group of select.querySelectorAll('optgroup')) {
      const options = [...group.querySelectorAll('option')].filter(o => `${o.value} ${o.textContent}`.toLowerCase().includes(q));
      if (!options.length) continue;
      const heading = document.createElement('h3'); heading.className = 'model-group';
      heading.textContent = group.label; list.append(heading);
      for (const option of options) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'model-option';
        button.setAttribute('aria-pressed', String(option.selected));
        const label = document.createElement('span'), title = document.createElement('span'), detail = document.createElement('small');
        title.textContent = name(option.textContent);
        detail.textContent = option.value;
        label.append(title, detail); button.append(label);
        if (option.selected) { const check = document.createElement('span'); check.className = 'check'; check.textContent = '✓'; button.append(check); }
        button.onclick = () => { select.value = option.value; select.dispatchEvent(new Event('change', { bubbles: true })); update(); dialog.close(); };
        list.append(button); count++;
      }
    }
    if (!count) { const empty = document.createElement('p'); empty.className = 'model-empty'; empty.textContent = 'No matching models. Try a different name.'; list.append(empty); }
  }
  trigger.onclick = () => { search.value = ''; render(); dialog.showModal(); search.focus(); };
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.addEventListener('close', () => trigger.focus());
  dialog.addEventListener('click', e => { const r = dialog.getBoundingClientRect(); if (e.target === dialog && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) dialog.close(); });
  search.addEventListener('input', render);
  search.addEventListener('keydown', e => { if (e.key === 'ArrowDown') { e.preventDefault(); list.querySelector('button')?.focus(); } });
  list.addEventListener('keydown', e => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    const buttons = [...list.querySelectorAll('button')], i = buttons.indexOf(document.activeElement);
    e.preventDefault(); buttons[e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus();
  });
  select.addEventListener('change', update);
  new MutationObserver(update).observe(select, { childList: true, subtree: true });
  select.after(trigger); select.hidden = true; update();

  // Every waveform corresponds to an actual successful /v1/health response.
  const canvas = $('health-pulse'), ctx = canvas.getContext('2d');
  const caption = document.createElement('p'); caption.className = 'pulse-caption';
  caption.textContent = 'No health sample yet'; canvas.parentElement.after(caption);
  let beats = [], lastHealth = null, lastSample = 0, lastFrame = 0;
  document.addEventListener('jarvis:health', e => {
    lastHealth = e.detail;
    if (e.detail.health) {
      lastSample = performance.now();
      beats.push({ at: lastSample, color: e.detail.degraded ? '#ff6176' : e.detail.health.busy ? '#ffb544' : '#46a5ff' });
      caption.textContent = `HEARTH RESPONSE · ${e.detail.latency} ms · checks every 5s`;
    } else caption.textContent = 'HEALTH CHECK FAILED · no live telemetry';
  });
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function pulse(now) {
    requestAnimationFrame(pulse);
    if (document.hidden || $('inspector').hidden || now - lastFrame < 65 || !ctx) return;
    lastFrame = now;
    const rect = canvas.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2), w = rect.width, h = rect.height;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.strokeStyle = '#35516b'; ctx.lineWidth = 1; ctx.stroke();
    beats = beats.filter(b => now - b.at < 20000);
    if (reduced.matches) { ctx.fillStyle = lastHealth?.health ? '#46a5ff' : '#ff6176'; ctx.beginPath(); ctx.arc(w / 2, h / 2, 3, 0, Math.PI * 2); ctx.fill(); return; }
    for (const beat of beats) {
      const x = w - (now - beat.at) / 20000 * w;
      ctx.beginPath(); ctx.moveTo(x - 17, h / 2);
      for (const [dx, dy] of [[-10,0],[-6,-8],[-2,10],[3,-32],[8,25],[12,0],[18,0]]) ctx.lineTo(x + dx, h / 2 + dy);
      ctx.strokeStyle = beat.color; ctx.shadowColor = beat.color; ctx.shadowBlur = 9; ctx.lineWidth = 1.4; ctx.stroke(); ctx.shadowBlur = 0;
    }
    if (lastHealth?.health && now - lastSample > 15000) caption.textContent = 'AWAITING HEALTH CHECK · last sample is stale';
  }
  requestAnimationFrame(pulse);

  // Optional read-aloud uses the browser's voice. Core motion follows real events.
  let speechId = 0, speechBar = null;
  function stopSpeech() {
    speechId++; window.speechSynthesis?.cancel(); window.JarvisCore?.setSpeaking(false);
    speechBar?.remove(); speechBar = null;
  }
  document.addEventListener('jarvis:speak', e => {
    stopSpeech();
    const id = speechId, text = e.detail.text;
    const chunks = text.match(/[^.!?\n]+[.!?\n]*|[.!?\n]+/g) || [text];
    speechBar = document.createElement('div'); speechBar.className = 'speech-bar'; speechBar.setAttribute('role', 'status');
    speechBar.innerHTML = '<canvas data-core="speaking" aria-hidden="true"></canvas><span>JARVIS · preparing browser voice</span><button type="button">Stop reading</button>';
    document.querySelector('.composer-zone').prepend(speechBar);
    speechBar.querySelector('button').onclick = stopSpeech;
    let i = 0;
    function next() {
      if (id !== speechId) return;
      if (i >= chunks.length) { stopSpeech(); return; }
      const utterance = new SpeechSynthesisUtterance(chunks[i++]);
      utterance.onstart = () => { if (id !== speechId) return; window.JarvisCore?.setSpeaking(true); speechBar.querySelector('span').textContent = 'JARVIS · speaking with browser voice'; };
      utterance.onboundary = () => window.JarvisCore?.word();
      utterance.onend = next;
      utterance.onerror = event => { if (id !== speechId) return; stopSpeech(); const toast = $('toast'); toast.textContent = `Browser voice unavailable (${event.error}). Your full answer remains above.`; toast.hidden = false; setTimeout(() => { toast.hidden = true; }, 4500); };
      speechSynthesis.speak(utterance);
    }
    next();
  });
  $('new-chat').addEventListener('click', stopSpeech);
  $('sessions').addEventListener('click', e => { if (e.target.closest('button')) stopSpeech(); });
  $('composer').addEventListener('submit', stopSpeech);
  addEventListener('pagehide', stopSpeech);
})();
