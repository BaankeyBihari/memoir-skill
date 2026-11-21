(function () {
  const THEME_STORAGE_KEY = 'memoir-ui.theme';
  const changeListeners = new Set();
  let eventCount = 0;
  let eventSource = null;

  function applyTheme(theme) {
    const allowed = new Set([
      'midnight',
      'rose-pine',
      'rose-pine-dawn',
      'solarized-dark',
      'solarized-light',
      'sky-light',
      'zinc-light'
    ]);
    const t = allowed.has(theme) ? theme : 'midnight';
    if (t === 'midnight') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', t);
    }
    const sel = document.getElementById('themeSelect');
    if (sel) sel.value = t;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, t);
    } catch (_) {}
  }

  function initTheme() {
    let saved = 'midnight';
    try {
      saved = localStorage.getItem(THEME_STORAGE_KEY) || 'midnight';
    } catch (_) {}
    applyTheme(saved);
  }

  function showToast(msg, kind) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    while (container.children.length >= 4) {
      container.removeChild(container.firstChild);
    }
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || 'info');
    const text = document.createElement('span');
    text.textContent = msg;
    const closeBtn = document.createElement('button');
    closeBtn.className = 'toast-close';
    closeBtn.type = 'button';
    closeBtn.textContent = '×';
    closeBtn.onclick = function () { el.remove(); };
    el.appendChild(text);
    el.appendChild(closeBtn);
    container.appendChild(el);
    setTimeout(function () {
      if (el.parentNode) el.remove();
    }, 4000);
  }

  function setSSEStatus(state, label) {
    const pill = document.getElementById('sseStatus');
    const text = document.getElementById('sseStatusText');
    const hero = document.getElementById('heroStreamState');
    if (pill) {
      pill.classList.remove('live', 'error');
      if (state) pill.classList.add(state);
    }
    if (text) text.textContent = label;
    if (hero) hero.textContent = label;
  }

  function recordEventRow(ev) {
    eventCount += 1;
    const countEl = document.getElementById('heroEventCount');
    if (countEl) countEl.textContent = String(eventCount);

    const empty = document.getElementById('eventLogEmpty');
    const wrap = document.getElementById('eventLogWrap');
    const body = document.getElementById('eventLogBody');
    if (!body) return;

    if (empty) empty.classList.add('hidden');
    if (wrap) wrap.classList.remove('hidden');

    const tr = document.createElement('tr');
    const tdTime = document.createElement('td');
    tdTime.className = 'mono';
    tdTime.textContent = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

    const tdOp = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'badge accent';
    badge.textContent = ev.op || ev.type || 'change';
    tdOp.appendChild(badge);

    const tdPath = document.createElement('td');
    tdPath.className = 'mono';
    tdPath.textContent = ev.path || '(store)';

    tr.appendChild(tdTime);
    tr.appendChild(tdOp);
    tr.appendChild(tdPath);
    body.insertBefore(tr, body.firstChild);

    while (body.children.length > 50) {
      body.removeChild(body.lastChild);
    }
  }

  function clearEventLog() {
    eventCount = 0;
    const countEl = document.getElementById('heroEventCount');
    if (countEl) countEl.textContent = '0';
    const body = document.getElementById('eventLogBody');
    if (body) body.innerHTML = '';
    const empty = document.getElementById('eventLogEmpty');
    const wrap = document.getElementById('eventLogWrap');
    if (empty) empty.classList.remove('hidden');
    if (wrap) wrap.classList.add('hidden');
  }

  async function refreshState() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('health returned ' + res.status);
      const data = await res.json();

      const pill = document.getElementById('storePathBadge');
      if (pill) {
        pill.textContent = data.store || '-';
        pill.title = data.store || '';
      }
      const heroStore = document.getElementById('heroStorePath');
      if (heroStore) heroStore.textContent = data.store || '-';

      const portEl = document.getElementById('serverPortValue');
      if (portEl) portEl.textContent = data.port ? String(data.port) : '-';

      const badge = document.getElementById('storeExistsBadge');
      if (badge) {
        badge.className = 'badge ' + (data.store_exists ? 'ok' : 'warn');
        badge.textContent = data.store_exists ? 'ready' : 'not initialized';
      }
    } catch (err) {
      showToast('Failed to reach memoir-ui server', 'error');
    }
  }

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }
    setSSEStatus('', 'Connecting');
    eventSource = new EventSource('/events');

    eventSource.addEventListener('connected', function () {
      setSSEStatus('live', 'Live');
    });

    eventSource.addEventListener('change', function (msg) {
      let ev = { type: 'change' };
      try {
        ev = JSON.parse(msg.data);
      } catch (_) {}
      recordEventRow(ev);
      changeListeners.forEach(function (fn) {
        try {
          fn(ev);
        } catch (_) {}
      });
    });

    eventSource.onerror = function () {
      setSSEStatus('error', 'Reconnecting...');
    };
  }

  window.applyTheme = applyTheme;
  window.refreshState = refreshState;
  window.clearEventLog = clearEventLog;
  window.memoirEvents = {
    onStoreChange: function (fn) {
      changeListeners.add(fn);
      return function () { changeListeners.delete(fn); };
    }
  };

  initTheme();
  refreshState();
  connectSSE();
})();
