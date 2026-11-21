(function () {
  const THEME_STORAGE_KEY = 'memoir-ui.theme';
  const expandedNodes = new Set();
  const knownDefaultExpanded = new Set();
  const changeListeners = new Set();
  let currentTree = null;
  let activeFilePath = '';
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

    while (body.children.length > 30) {
      body.removeChild(body.lastChild);
    }
  }

  function clearEventLog() {
    const body = document.getElementById('eventLogBody');
    if (body) body.innerHTML = '';
    const empty = document.getElementById('eventLogEmpty');
    const wrap = document.getElementById('eventLogWrap');
    if (empty) empty.classList.remove('hidden');
    if (wrap) wrap.classList.add('hidden');
  }

  function isExpanded(id, defaultOpen) {
    if (!knownDefaultExpanded.has(id)) {
      knownDefaultExpanded.add(id);
      if (defaultOpen) expandedNodes.add(id);
    }
    return expandedNodes.has(id);
  }

  function toggleNode(id) {
    if (expandedNodes.has(id)) {
      expandedNodes.delete(id);
    } else {
      expandedNodes.add(id);
    }
    renderTree();
  }

  function setAllExpanded(open) {
    if (!currentTree) return;
    knownDefaultExpanded.forEach(function (id) {
      if (open) expandedNodes.add(id);
      else expandedNodes.delete(id);
    });
    renderTree();
  }

  function createCollapsibleGroup(id, label, defaultOpen, strong, tooltip, badgeText, buildChildren) {
    const open = isExpanded(id, defaultOpen);
    const wrap = document.createElement('div');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tree-node-btn';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (tooltip) btn.title = tooltip;
    btn.onclick = function () { toggleNode(id); };

    const chev = document.createElement('span');
    chev.className = 'tree-chevron';
    chev.textContent = open ? '▾' : '▸';

    const lbl = document.createElement('span');
    lbl.className = 'tree-label' + (strong ? ' strong' : '');
    lbl.textContent = label;

    btn.appendChild(chev);
    btn.appendChild(lbl);

    if (badgeText) {
      const b = document.createElement('span');
      b.className = 'tree-count';
      b.textContent = badgeText;
      btn.appendChild(b);
    }

    wrap.appendChild(btn);

    if (open) {
      const children = document.createElement('div');
      children.className = 'tree-children';
      buildChildren(children);
      wrap.appendChild(children);
    }
    return wrap;
  }

  function kindShortLabel(kind) {
    switch (kind) {
      case 'wiki': return 'wiki';
      case 'decision': return 'dec';
      case 'state': return 'state';
      case 'log': return 'log';
      case 'reference': return 'ref';
      case 'feedback': return 'fb';
      default: return 'md';
    }
  }

  function createFileItem(node) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tree-file-btn' + (activeFilePath === node.path ? ' active' : '');
    btn.title = node.path;
    btn.onclick = function () { navigateToFile(node.path); };

    const kind = document.createElement('span');
    kind.className = 'kind-dot kind-' + (node.kind || 'other');
    kind.textContent = kindShortLabel(node.kind);

    const lbl = document.createElement('span');
    lbl.className = 'tree-label';
    lbl.textContent = node.name;

    btn.appendChild(kind);
    btn.appendChild(lbl);
    return btn;
  }

  function appendWikiBranch(container, scopeKey, wiki) {
    if (!wiki) return;
    const total = (wiki.top_pages || []).length +
      (wiki.categories || []).reduce(function (acc, c) { return acc + (c.pages || []).length; }, 0);
    if (total === 0) return;

    container.appendChild(createCollapsibleGroup(
      'wiki:' + scopeKey,
      'Wiki',
      true,
      true,
      'Shared compiled wiki',
      String(total),
      function (wikiEl) {
        (wiki.top_pages || []).forEach(function (page) {
          wikiEl.appendChild(createFileItem(page));
        });
        (wiki.categories || []).forEach(function (cat) {
          wikiEl.appendChild(createCollapsibleGroup(
            'cat:' + scopeKey + ':' + cat.name,
            cat.name + '/',
            true,
            false,
            '',
            String((cat.pages || []).length),
            function (catEl) {
              (cat.pages || []).forEach(function (page) {
                catEl.appendChild(createFileItem(page));
              });
            }
          ));
        });
      }
    ));
  }

  function appendActiveArchiveBranch(container, nodePrefix, stateNode, activeList, archiveList) {
    if (stateNode) {
      container.appendChild(createFileItem(stateNode));
    }
    if ((activeList || []).length > 0) {
      container.appendChild(createCollapsibleGroup(
        nodePrefix + ':active',
        'active/',
        true,
        false,
        '',
        String(activeList.length),
        function (actEl) {
          activeList.forEach(function (f) { actEl.appendChild(createFileItem(f)); });
        }
      ));
    }
    if ((archiveList || []).length > 0) {
      container.appendChild(createCollapsibleGroup(
        nodePrefix + ':archive',
        'archive/',
        false,
        false,
        '',
        String(archiveList.length),
        function (archEl) {
          archiveList.forEach(function (f) { archEl.appendChild(createFileItem(f)); });
        }
      ));
    }
  }

  function appendPathsBranch(container, scopeKey, paths) {
    (paths || []).forEach(function (p) {
      const count = (p.state ? 1 : 0) + (p.active || []).length + (p.archive || []).length;
      container.appendChild(createCollapsibleGroup(
        'path:' + scopeKey + ':' + p.key,
        p.label,
        true,
        false,
        p.key,
        String(count),
        function (pathEl) {
          appendActiveArchiveBranch(pathEl, 'path:' + scopeKey + ':' + p.key, p.state, p.active, p.archive);
        }
      ));
    });
  }

  function createSection(title, count) {
    const sec = document.createElement('div');
    sec.className = 'tree-section';
    const header = document.createElement('div');
    header.className = 'tree-section-title';
    const t = document.createElement('span');
    t.textContent = title;
    const c = document.createElement('span');
    c.className = 'tree-count';
    c.textContent = String(count);
    header.appendChild(t);
    header.appendChild(c);
    sec.appendChild(header);
    return sec;
  }

  function renderTree() {
    const root = document.getElementById('sidebarTree');
    if (!root) return;
    root.innerHTML = '';

    if (!currentTree) {
      const loading = document.createElement('div');
      loading.className = 'tree-empty';
      loading.textContent = 'Loading store...';
      root.appendChild(loading);
      return;
    }

    const repos = currentTree.repos || [];
    const pinned = currentTree.pinned || [];
    const standalone = currentTree.standalone || [];

    // 1. Repos
    const reposSec = createSection('Repos', repos.length);
    if (repos.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'tree-empty';
      empty.textContent = 'No repositories yet';
      reposSec.appendChild(empty);
    } else {
      repos.forEach(function (repo) {
        reposSec.appendChild(createCollapsibleGroup(
          'repo:' + repo.id,
          repo.label,
          true,
          true,
          repo.meta && repo.meta.remote ? repo.meta.remote : repo.id,
          '',
          function (repoEl) {
            appendWikiBranch(repoEl, 'repo:' + repo.id, repo.wiki);
            (repo.clones || []).forEach(function (clone) {
              repoEl.appendChild(createCollapsibleGroup(
                'clone:' + repo.id + ':' + clone.id,
                clone.label,
                true,
                false,
                clone.root || clone.rel_path,
                String((clone.paths || []).length),
                function (cloneEl) {
                  appendPathsBranch(cloneEl, 'clone:' + repo.id + ':' + clone.id, clone.paths);
                }
              ));
            });
          }
        ));
      });
    }
    root.appendChild(reposSec);

    // 2. Pinned Workspaces
    const pinnedSec = createSection('Pinned Workspaces', pinned.length);
    if (pinned.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'tree-empty';
      empty.textContent = 'No pinned workspaces';
      pinnedSec.appendChild(empty);
    } else {
      pinned.forEach(function (pin) {
        pinnedSec.appendChild(createCollapsibleGroup(
          'pinned:' + pin.id,
          pin.label,
          true,
          true,
          pin.root || pin.rel_path,
          '',
          function (pinEl) {
            appendWikiBranch(pinEl, 'pinned:' + pin.id, pin.wiki);
            appendPathsBranch(pinEl, 'pinned:' + pin.id, pin.paths);
          }
        ));
      });
    }
    root.appendChild(pinnedSec);

    // 3. Standalone
    const standaloneSec = createSection('Standalone', standalone.length);
    if (standalone.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'tree-empty';
      empty.textContent = 'No standalone workspaces';
      standaloneSec.appendChild(empty);
    } else {
      standalone.forEach(function (st) {
        const count = (st.state ? 1 : 0) + (st.active || []).length + (st.archive || []).length;
        standaloneSec.appendChild(createCollapsibleGroup(
          'standalone:' + st.id,
          st.label,
          true,
          true,
          st.id,
          String(count),
          function (stEl) {
            appendActiveArchiveBranch(stEl, 'standalone:' + st.id, st.state, st.active, st.archive);
          }
        ));
      });
    }
    root.appendChild(standaloneSec);
  }

  function updateOverviewStats() {
    if (!currentTree) return;
    const repos = (currentTree.repos || []).length;
    const pinned = (currentTree.pinned || []).length;
    const standalone = (currentTree.standalone || []).length;

    const rEl = document.getElementById('statReposCount');
    const pEl = document.getElementById('statPinnedCount');
    const sEl = document.getElementById('statStandaloneCount');
    if (rEl) rEl.textContent = String(repos);
    if (pEl) pEl.textContent = String(pinned);
    if (sEl) sEl.textContent = String(standalone);

    const emptyCard = document.getElementById('emptyStoreCard');
    const emptyPath = document.getElementById('emptyStorePath');
    if (emptyCard) {
      if (repos + pinned + standalone === 0) {
        emptyCard.classList.remove('hidden');
        if (emptyPath) emptyPath.textContent = currentTree.store_root || '~/.memoir';
      } else {
        emptyCard.classList.add('hidden');
      }
    }
  }

  async function refreshTree() {
    try {
      const res = await fetch('/api/tree');
      if (!res.ok) throw new Error('tree failed');
      currentTree = await res.json();
      const pill = document.getElementById('storePathBadge');
      if (pill && currentTree.store_root) {
        pill.textContent = currentTree.store_root;
        pill.title = currentTree.store_root;
      }
      renderTree();
      updateOverviewStats();
    } catch (_) {
      showToast('Failed to load Memoir store tree', 'error');
    }
  }

  function parseHashFile() {
    const hash = window.location.hash || '';
    if (!hash.startsWith('#file=')) return '';
    try {
      return decodeURIComponent(hash.slice('#file='.length));
    } catch (_) {
      return '';
    }
  }

  function navigateToFile(relPath) {
    if (!relPath) {
      clearSelection();
      return;
    }
    const targetHash = '#file=' + encodeURIComponent(relPath);
    if (window.location.hash !== targetHash) {
      window.location.hash = targetHash;
    } else {
      loadFile(relPath);
    }
  }

  function clearSelection(ev) {
    if (ev) ev.preventDefault();
    activeFilePath = '';
    if (window.location.hash) {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    showOverviewView();
    renderTree();
  }

  function showOverviewView() {
    document.getElementById('overviewView').classList.remove('hidden');
    document.getElementById('documentView').classList.add('hidden');
  }

  function showDocumentView(doc) {
    document.getElementById('overviewView').classList.add('hidden');
    document.getElementById('documentView').classList.remove('hidden');

    const crumb = document.getElementById('docBreadcrumb');
    if (crumb) {
      crumb.textContent = (doc.path || '').split('/').join(' / ');
    }
    document.getElementById('docTitle').textContent = doc.title || doc.name || doc.path;
    document.getElementById('docRelPath').textContent = doc.path || '';

    const badges = document.getElementById('docKindBadges');
    badges.innerHTML = '';
    if (doc.kind) {
      const k = document.createElement('span');
      k.className = 'badge accent';
      k.textContent = doc.kind;
      badges.appendChild(k);
    }
    if (doc.archived) {
      const a = document.createElement('span');
      a.className = 'badge warn';
      a.textContent = 'archived';
      badges.appendChild(a);
    }

    document.getElementById('docRawBody').textContent = doc.raw || '';
  }

  async function loadFile(relPath) {
    if (!relPath) {
      activeFilePath = '';
      showOverviewView();
      renderTree();
      return;
    }
    activeFilePath = relPath;
    renderTree();

    try {
      const res = await fetch('/api/file?path=' + encodeURIComponent(relPath));
      if (!res.ok) {
        const err = await res.json().catch(function () { return {}; });
        showToast(err.error || 'Failed to open file', 'error');
        if (res.status === 404) {
          showOverviewView();
        }
        return;
      }
      const doc = await res.json();
      showDocumentView(doc);
    } catch (_) {
      showToast('Failed to load file', 'error');
    }
  }

  async function refreshAll() {
    await refreshTree();
    if (activeFilePath) {
      await loadFile(activeFilePath);
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
      refreshAll();
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

  window.addEventListener('hashchange', function () {
    const target = parseHashFile();
    if (target) loadFile(target);
    else {
      activeFilePath = '';
      showOverviewView();
      renderTree();
    }
  });

  window.applyTheme = applyTheme;
  window.refreshAll = refreshAll;
  window.clearEventLog = clearEventLog;
  window.clearSelection = clearSelection;
  window.setAllExpanded = setAllExpanded;
  window.navigateToFile = navigateToFile;
  window.memoirEvents = {
    onStoreChange: function (fn) {
      changeListeners.add(fn);
      return function () { changeListeners.delete(fn); };
    }
  };

  initTheme();
  connectSSE();
  refreshTree().then(function () {
    const initial = parseHashFile();
    if (initial) {
      loadFile(initial);
    }
  });
})();
