(function () {
  const THEME_STORAGE_KEY = 'memoir-ui.theme';
  const SIDEBAR_WIDTH_STORAGE_KEY = 'memoir-ui.sidebarWidth';
  const SIDEBAR_DEFAULT_WIDTH = 320;
  const SIDEBAR_MIN_WIDTH = 220;
  const SIDEBAR_MAX_WIDTH = 640;

  const HASH_FILE_PREFIX = '#file=';
  const CLS_BADGE_ACCENT = 'badge accent';
  const CLS_BADGE_WARN = 'badge warn';
  const CLS_BADGE_DANGER = 'badge danger';
  const CLS_TREE_EMPTY = 'tree-empty';
  const CLS_EMPTY_NOTE = 'empty-note';
  const COLOR_MUTED = 'var(--muted)';
  const PREFIX_PINNED = 'pinned:';

  const expandedNodes = new Set();
  const knownDefaultExpanded = new Set();
  const changeListeners = new Set();
  let currentTree = null;
  let currentOrphans = [];
  let activeFilePath = '';
  let docViewMode = 'rendered';
  let eventSource = null;
  let searchScopeFilter = '';
  let searchTypeFilter = '';
  let searchResultsList = [];
  let searchSelectedIdx = 0;
  let searchTimer = null;
  let pendingPruneTarget = null;
  let savedSidebarWidth = SIDEBAR_DEFAULT_WIDTH;

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function safeStorageSet(key, val) {
    try {
      localStorage.setItem(key, val);
    } catch {
      // Ignore storage write errors in private or sandboxed browser modes.
    }
  }

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
    safeStorageSet(THEME_STORAGE_KEY, t);
  }

  function initTheme() {
    applyTheme(safeStorageGet(THEME_STORAGE_KEY) || 'midnight');
  }

  function clampSidebarWidth(width) {
    const viewportCap = Math.max(SIDEBAR_MIN_WIDTH, globalThis.innerWidth - 280);
    const maxW = Math.min(SIDEBAR_MAX_WIDTH, viewportCap);
    return Math.round(Math.min(maxW, Math.max(SIDEBAR_MIN_WIDTH, width)));
  }

  function applySidebarWidth(width, persist) {
    const clamped = clampSidebarWidth(width);
    document.documentElement.style.setProperty('--sidebar-width', clamped + 'px');
    const resizer = document.getElementById('sidebarResizer');
    if (resizer) {
      resizer.setAttribute('aria-valuenow', String(clamped));
    }
    if (persist) {
      savedSidebarWidth = clamped;
      safeStorageSet(SIDEBAR_WIDTH_STORAGE_KEY, String(clamped));
    }
    return clamped;
  }

  function readSavedSidebarWidth() {
    const stored = Number.parseInt(safeStorageGet(SIDEBAR_WIDTH_STORAGE_KEY) || '', 10);
    if (!Number.isNaN(stored) && stored >= SIDEBAR_MIN_WIDTH && stored <= SIDEBAR_MAX_WIDTH) {
      return stored;
    }
    return SIDEBAR_DEFAULT_WIDTH;
  }

  function releasePointerSafely(resizer, ev) {
    if (!ev || typeof ev.pointerId !== 'number' || !resizer.hasPointerCapture || !resizer.hasPointerCapture(ev.pointerId)) {
      return;
    }
    try {
      resizer.releasePointerCapture(ev.pointerId);
    } catch {
      // Ignore if pointer capture already ended before release.
    }
  }

  function onResizerKeyDown(ev, sidebar) {
    const step = ev.shiftKey ? 40 : 20;
    if (ev.key === 'ArrowRight') {
      ev.preventDefault();
      applySidebarWidth(sidebar.getBoundingClientRect().width + step, true);
    } else if (ev.key === 'ArrowLeft') {
      ev.preventDefault();
      applySidebarWidth(sidebar.getBoundingClientRect().width - step, true);
    } else if (ev.key === 'Home') {
      ev.preventDefault();
      applySidebarWidth(SIDEBAR_DEFAULT_WIDTH, true);
    }
  }

  function initSidebarResize() {
    savedSidebarWidth = readSavedSidebarWidth();
    applySidebarWidth(savedSidebarWidth, false);

    const resizer = document.getElementById('sidebarResizer');
    const sidebar = document.getElementById('sidebar');
    if (!resizer || !sidebar) return;

    let dragging = false;
    let startX = 0;
    let startWidth = SIDEBAR_DEFAULT_WIDTH;
    let lastWidth = SIDEBAR_DEFAULT_WIDTH;

    function finishDrag(ev) {
      if (!dragging) return;
      dragging = false;
      resizer.classList.remove('resizing');
      document.body.classList.remove('is-resizing-sidebar');
      releasePointerSafely(resizer, ev);
      applySidebarWidth(lastWidth, true);
    }

    resizer.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) return;
      ev.preventDefault();
      dragging = true;
      startX = ev.clientX;
      startWidth = sidebar.getBoundingClientRect().width;
      lastWidth = startWidth;
      resizer.classList.add('resizing');
      document.body.classList.add('is-resizing-sidebar');
      if (typeof ev.pointerId === 'number' && resizer.setPointerCapture) {
        try {
          resizer.setPointerCapture(ev.pointerId);
        } catch {
          // Ignore synthetic or non-primary pointer capture failures.
        }
      }
    });

    globalThis.addEventListener('pointermove', function (ev) {
      if (!dragging) return;
      lastWidth = applySidebarWidth(startWidth + (ev.clientX - startX), false);
    });
    globalThis.addEventListener('pointerup', finishDrag);
    globalThis.addEventListener('pointercancel', finishDrag);
    resizer.addEventListener('dblclick', function () { applySidebarWidth(SIDEBAR_DEFAULT_WIDTH, true); });
    resizer.addEventListener('keydown', function (ev) { onResizerKeyDown(ev, sidebar); });
    globalThis.addEventListener('resize', function () { applySidebarWidth(savedSidebarWidth, false); });
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
    badge.className = CLS_BADGE_ACCENT;
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

  function createCollapsibleGroup(opts) {
    const open = isExpanded(opts.id, opts.defaultOpen);
    const wrap = document.createElement('div');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tree-node-btn';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (opts.tooltip) btn.title = opts.tooltip;
    btn.onclick = function () { toggleNode(opts.id); };

    const chev = document.createElement('span');
    chev.className = 'tree-chevron';
    chev.textContent = open ? '▾' : '▸';

    const lbl = document.createElement('span');
    lbl.className = 'tree-label' + (opts.strong ? ' strong' : '');
    lbl.textContent = opts.label;

    btn.appendChild(chev);
    btn.appendChild(lbl);

    if (opts.badgeText) {
      const b = document.createElement('span');
      b.className = 'tree-count';
      b.textContent = opts.badgeText;
      btn.appendChild(b);
    }

    wrap.appendChild(btn);

    if (open) {
      const children = document.createElement('div');
      children.className = 'tree-children';
      opts.buildChildren(children);
      wrap.appendChild(children);
    }
    return wrap;
  }

  function kindShortLabel(kind) {
    switch (kind) {
      case 'wiki': return 'wiki';
      case 'decision': return 'dec';
      case 'state': return 'state';
      case 'task': return 'task';
      case 'log': return 'log';
      case 'reference': return 'ref';
      case 'feedback': return 'fb';
      default: return 'md';
    }
  }

  function formatTreeFileLabel(node) {
    const raw = node && node.name ? String(node.name) : '';
    if (!raw) return '';
    let name = raw.replace(/\.md$/i, '');
    let datePrefix = '';
    const dateMatch = name.match(/^(\d{8}-)(.+)$/);
    if (dateMatch) {
      datePrefix = dateMatch[1];
      name = dateMatch[2];
    }
    const prefixByKind = {
      decision: 'decision-',
      log: 'log-',
      reference: 'reference-',
      task: 'task-',
      feedback: 'feedback-',
      state: 'state-'
    };
    const prefix = prefixByKind[node.kind];
    if (prefix && name.startsWith(prefix) && name.length > prefix.length) {
      name = name.slice(prefix.length);
    }
    return (datePrefix + name) || raw;
  }

  function createFileItem(node) {
    const link = document.createElement('a');
    link.href = HASH_FILE_PREFIX + encodeURIComponent(node.path);
    link.className = 'tree-file-btn' + (activeFilePath === node.path ? ' active' : '');
    link.title = node.path;
    link.onclick = function (ev) {
      if (link.hash === globalThis.location.hash && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey && !ev.altKey) {
        ev.preventDefault();
        loadFile(node.path);
      }
    };

    const kind = document.createElement('span');
    kind.className = 'kind-dot kind-' + (node.kind || 'other');
    kind.textContent = kindShortLabel(node.kind);

    const lbl = document.createElement('span');
    lbl.className = 'tree-label';
    lbl.textContent = formatTreeFileLabel(node);

    link.appendChild(kind);
    link.appendChild(lbl);
    return link;
  }

  function appendWikiBranch(container, scopeKey, wiki) {
    if (!wiki) return;
    const total = (wiki.top_pages || []).length +
      (wiki.categories || []).reduce(function (acc, c) { return acc + (c.pages || []).length; }, 0);
    if (total === 0) return;

    container.appendChild(createCollapsibleGroup({
      id: 'wiki:' + scopeKey,
      label: 'Wiki',
      defaultOpen: true,
      strong: true,
      tooltip: 'Shared compiled wiki',
      badgeText: String(total),
      buildChildren: function (wikiEl) {
        (wiki.top_pages || []).forEach(function (page) {
          wikiEl.appendChild(createFileItem(page));
        });
        (wiki.categories || []).forEach(function (cat) {
          wikiEl.appendChild(createCollapsibleGroup({
            id: 'cat:' + scopeKey + ':' + cat.name,
            label: cat.name + '/',
            defaultOpen: true,
            strong: false,
            tooltip: '',
            badgeText: String((cat.pages || []).length),
            buildChildren: function (catEl) {
              (cat.pages || []).forEach(function (page) { catEl.appendChild(createFileItem(page)); });
            }
          }));
        });
      }
    }));
  }

  function appendActiveArchiveBranch(container, nodePrefix, stateNode, activeList, archiveList) {
    if (stateNode) {
      container.appendChild(createFileItem(stateNode));
    }
    if ((activeList || []).length > 0) {
      container.appendChild(createCollapsibleGroup({
        id: nodePrefix + ':active',
        label: 'active/',
        defaultOpen: true,
        strong: false,
        tooltip: '',
        badgeText: String(activeList.length),
        buildChildren: function (actEl) {
          activeList.forEach(function (f) { actEl.appendChild(createFileItem(f)); });
        }
      }));
    }
    if ((archiveList || []).length > 0) {
      container.appendChild(createCollapsibleGroup({
        id: nodePrefix + ':archive',
        label: 'archive/',
        defaultOpen: false,
        strong: false,
        tooltip: '',
        badgeText: String(archiveList.length),
        buildChildren: function (archEl) {
          archiveList.forEach(function (f) { archEl.appendChild(createFileItem(f)); });
        }
      }));
    }
  }

  function appendPathsBranch(container, scopeKey, paths) {
    (paths || []).forEach(function (p) {
      const count = (p.state ? 1 : 0) + (p.active || []).length + (p.archive || []).length;
      const nodeId = 'path:' + scopeKey + ':' + p.key;
      container.appendChild(createCollapsibleGroup({
        id: nodeId,
        label: p.label,
        defaultOpen: true,
        strong: false,
        tooltip: p.key,
        badgeText: String(count),
        buildChildren: function (pathEl) {
          appendActiveArchiveBranch(pathEl, nodeId, p.state, p.active, p.archive);
        }
      }));
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

  function appendEmptyTreeNote(sec, msg) {
    const empty = document.createElement('div');
    empty.className = CLS_TREE_EMPTY;
    empty.textContent = msg;
    sec.appendChild(empty);
  }

  function renderReposSection(repos) {
    const sec = createSection('Repos', repos.length);
    if (repos.length === 0) {
      appendEmptyTreeNote(sec, 'No repositories yet');
      return sec;
    }
    repos.forEach(function (repo) {
      sec.appendChild(createCollapsibleGroup({
        id: 'repo:' + repo.id,
        label: repo.label,
        defaultOpen: true,
        strong: true,
        tooltip: repo.meta && repo.meta.remote ? repo.meta.remote : repo.id,
        badgeText: '',
        buildChildren: function (repoEl) {
          appendWikiBranch(repoEl, 'repo:' + repo.id, repo.wiki);
          (repo.clones || []).forEach(function (clone) {
            const cloneKey = repo.id + ':' + clone.id;
            const group = createCollapsibleGroup({
              id: 'clone:' + cloneKey,
              label: clone.label,
              defaultOpen: true,
              strong: false,
              tooltip: clone.root || clone.rel_path,
              badgeText: String((clone.paths || []).length),
              buildChildren: function (cloneEl) {
                appendPathsBranch(cloneEl, 'clone:' + cloneKey, clone.paths);
              }
            });
            if (clone.orphaned) {
              decorateOrphanGroup(group, {
                scope: 'clone',
                id: clone.id,
                rel_path: clone.rel_path,
                root: clone.root || ''
              });
            }
            repoEl.appendChild(group);
          });
        }
      }));
    });
    return sec;
  }

  function renderPinnedSection(pinned) {
    const sec = createSection('Pinned Workspaces', pinned.length);
    if (pinned.length === 0) {
      appendEmptyTreeNote(sec, 'No pinned workspaces');
      return sec;
    }
    pinned.forEach(function (pin) {
      const group = createCollapsibleGroup({
        id: PREFIX_PINNED + pin.id,
        label: pin.label,
        defaultOpen: true,
        strong: true,
        tooltip: pin.root || pin.rel_path,
        badgeText: '',
        buildChildren: function (pinEl) {
          appendWikiBranch(pinEl, PREFIX_PINNED + pin.id, pin.wiki);
          appendPathsBranch(pinEl, PREFIX_PINNED + pin.id, pin.paths);
        }
      });
      if (pin.orphaned) {
        decorateOrphanGroup(group, {
          scope: 'pinned',
          id: pin.id,
          rel_path: pin.rel_path,
          root: pin.root || ''
        });
      }
      sec.appendChild(group);
    });
    return sec;
  }

  function renderStandaloneSection(standalone) {
    const sec = createSection('Standalone', standalone.length);
    if (standalone.length === 0) {
      appendEmptyTreeNote(sec, 'No standalone workspaces');
      return sec;
    }
    standalone.forEach(function (st) {
      const count = (st.state ? 1 : 0) + (st.active || []).length + (st.archive || []).length;
      sec.appendChild(createCollapsibleGroup({
        id: 'standalone:' + st.id,
        label: st.label,
        defaultOpen: true,
        strong: true,
        tooltip: st.id,
        badgeText: String(count),
        buildChildren: function (stEl) {
          appendActiveArchiveBranch(stEl, 'standalone:' + st.id, st.state, st.active, st.archive);
        }
      }));
    });
    return sec;
  }

  function renderTree() {
    const root = document.getElementById('sidebarTree');
    if (!root) return;
    root.innerHTML = '';

    if (!currentTree) {
      appendEmptyTreeNote(root, 'Loading store...');
      return;
    }

    root.appendChild(renderReposSection(currentTree.repos || []));
    root.appendChild(renderPinnedSection(currentTree.pinned || []));
    root.appendChild(renderStandaloneSection(currentTree.standalone || []));
  }

  function setTextById(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value);
  }

  function updateOverviewStats() {
    if (!currentTree) return;
    const repos = (currentTree.repos || []).length;
    const pinned = (currentTree.pinned || []).length;
    const standalone = (currentTree.standalone || []).length;

    setTextById('statReposCount', repos);
    setTextById('statPinnedCount', pinned);
    setTextById('statStandaloneCount', standalone);

    const emptyCard = document.getElementById('emptyStoreCard');
    if (!emptyCard) return;
    if (repos + pinned + standalone === 0) {
      emptyCard.classList.remove('hidden');
      setTextById('emptyStorePath', currentTree.store_root || '~/.memoir');
    } else {
      emptyCard.classList.add('hidden');
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
    } catch {
      showToast('Failed to load Memoir store tree', 'error');
    }
  }

  function parseHashFile() {
    const hash = globalThis.location.hash || '';
    if (!hash.startsWith(HASH_FILE_PREFIX)) return '';
    try {
      return decodeURIComponent(hash.slice(HASH_FILE_PREFIX.length));
    } catch {
      return '';
    }
  }

  function navigateToFile(relPath) {
    if (!relPath) {
      clearSelection();
      return;
    }
    const targetHash = HASH_FILE_PREFIX + encodeURIComponent(relPath);
    if (globalThis.location.hash !== targetHash) {
      globalThis.location.hash = targetHash;
    } else {
      loadFile(relPath);
    }
  }

  function clearSelection(ev) {
    if (ev) ev.preventDefault();
    activeFilePath = '';
    if (globalThis.location.hash) {
      history.replaceState(null, '', globalThis.location.pathname + globalThis.location.search);
    }
    showOverviewView();
    renderTree();
  }

  function showOverviewView() {
    document.getElementById('overviewView').classList.remove('hidden');
    document.getElementById('documentView').classList.add('hidden');
  }

  function applyDocViewMode() {
    const rendered = document.getElementById('docRenderedBody');
    const raw = document.getElementById('docRawBody');
    const btn = document.getElementById('docViewToggle');
    if (!rendered || !raw || !btn) return;
    if (docViewMode === 'raw') {
      rendered.classList.add('hidden');
      raw.classList.remove('hidden');
      btn.textContent = 'Rendered';
    } else {
      raw.classList.add('hidden');
      rendered.classList.remove('hidden');
      btn.textContent = 'Raw';
    }
  }

  function toggleDocViewMode() {
    docViewMode = docViewMode === 'raw' ? 'rendered' : 'raw';
    applyDocViewMode();
  }

  function createMetadataBadgeEl(b) {
    const isLink = Boolean(b.target_path || b.url);
    const el = document.createElement(isLink ? 'a' : 'span');
    el.className = 'meta-badge';
    if (b.target_path) {
      el.href = HASH_FILE_PREFIX + encodeURIComponent(b.target_path);
      el.onclick = function (ev) {
        ev.preventDefault();
        navigateToFile(b.target_path);
      };
    } else if (b.url) {
      el.href = b.url;
      el.target = '_blank';
      el.rel = 'noopener noreferrer';
    }
    const k = document.createElement('span');
    k.className = 'meta-badge-key';
    k.textContent = b.key;
    const v = document.createElement('span');
    v.className = 'meta-badge-val mono';
    v.textContent = b.value;
    el.appendChild(k);
    el.appendChild(v);
    return el;
  }

  function renderBadgeBar(badges) {
    const bar = document.getElementById('docMetadataBar');
    bar.innerHTML = '';
    const items = badges || [];
    if (items.length === 0) {
      bar.classList.add('hidden');
      return;
    }
    bar.classList.remove('hidden');
    items.forEach(function (b) { bar.appendChild(createMetadataBadgeEl(b)); });
  }

  function renderSourcesBar(sources) {
    const srcBar = document.getElementById('docSourcesBar');
    srcBar.innerHTML = '';
    const srcItems = sources || [];
    if (srcItems.length === 0) {
      srcBar.classList.add('hidden');
      return;
    }
    srcBar.classList.remove('hidden');
    const lbl = document.createElement('span');
    lbl.className = 'sources-label';
    lbl.textContent = 'Sources:';
    srcBar.appendChild(lbl);

    srcItems.forEach(function (s) {
      const linked = Boolean(s.target_path && !s.broken);
      const el = document.createElement(linked ? 'a' : 'span');
      el.className = 'source-pill mono' + (s.broken ? ' broken' : '');
      el.textContent = s.label;
      if (linked) {
        el.href = HASH_FILE_PREFIX + encodeURIComponent(s.target_path);
        el.onclick = function (ev) {
          ev.preventDefault();
          navigateToFile(s.target_path);
        };
      }
      srcBar.appendChild(el);
    });
  }

  function renderMetadataBadges(badges, sources) {
    renderBadgeBar(badges);
    renderSourcesBar(sources);
  }

  function createArrowSvg() {
    const span = document.createElement('span');
    span.className = 'chain-arrow';
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>';
    return span;
  }

  function createDecisionStatusBadge(node) {
    const status = document.createElement('span');
    if (node.missing) {
      status.className = CLS_BADGE_DANGER;
      status.textContent = 'Missing';
    } else if (node.active_head) {
      status.className = 'badge ok';
      status.textContent = 'Active';
    } else if (node.archived) {
      status.className = CLS_BADGE_WARN;
      status.textContent = 'Archived';
    } else {
      status.className = CLS_BADGE_ACCENT;
      status.textContent = 'Decision';
    }
    return status;
  }

  function createDecisionNodeEl(node) {
    const el = document.createElement(node.missing || !node.path ? 'div' : 'button');
    if (el.tagName === 'BUTTON') {
      el.type = 'button';
      el.onclick = function () { navigateToFile(node.path); };
    }
    el.className = 'chain-node';
    if (node.current) el.classList.add('is-current');
    if (node.active_head) el.classList.add('is-active-head');
    if (node.missing) el.classList.add('is-missing');

    const top = document.createElement('div');
    top.className = 'chain-node-top';
    top.appendChild(createDecisionStatusBadge(node));

    if (node.date) {
      const dt = document.createElement('span');
      dt.className = 'mono';
      dt.style.fontSize = '0.72rem';
      dt.style.color = COLOR_MUTED;
      dt.textContent = node.date;
      top.appendChild(dt);
    }

    const title = document.createElement('div');
    title.className = 'chain-node-title';
    title.textContent = node.title || node.id;

    const idEl = document.createElement('div');
    idEl.className = 'chain-node-id mono';
    idEl.textContent = node.id;

    el.appendChild(top);
    el.appendChild(title);
    el.appendChild(idEl);
    return el;
  }

  function renderDecisionChain(chain) {
    const sec = document.getElementById('docDecisionChain');
    const track = document.getElementById('docChainTrack');
    track.innerHTML = '';
    if (!chain || !chain.nodes || chain.nodes.length === 0) {
      sec.classList.add('hidden');
      return;
    }
    sec.classList.remove('hidden');

    chain.nodes.forEach(function (node, idx) {
      if (idx > 0) {
        track.appendChild(createArrowSvg());
      }
      track.appendChild(createDecisionNodeEl(node));
    });
  }

  function renderBacklinks(doc) {
    const sec = document.getElementById('docBacklinks');
    const countEl = document.getElementById('docBacklinksCount');
    const list = document.getElementById('docBacklinksList');
    list.innerHTML = '';

    if (doc.kind !== 'wiki') {
      sec.classList.add('hidden');
      return;
    }

    sec.classList.remove('hidden');
    const items = doc.backlinks || [];
    countEl.textContent = String(items.length);

    if (items.length === 0) {
      const empty = document.createElement('div');
      empty.className = CLS_EMPTY_NOTE;
      empty.textContent = 'No inbound backlinks from other wiki pages yet.';
      list.appendChild(empty);
      return;
    }

    items.forEach(function (bl) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'backlink-card';
      card.onclick = function () { navigateToFile(bl.source_path); };

      const top = document.createElement('div');
      top.className = 'backlink-top';
      const title = document.createElement('span');
      title.className = 'backlink-title';
      title.textContent = bl.source_title || bl.source_path;
      top.appendChild(title);

      if (bl.cross_wiki) {
        const pill = document.createElement('span');
        pill.className = CLS_BADGE_ACCENT;
        pill.textContent = 'cross-wiki: ' + bl.source_scope;
        top.appendChild(pill);
      } else if (bl.kind && bl.kind !== 'page') {
        const pill = document.createElement('span');
        pill.className = 'badge';
        pill.textContent = bl.kind;
        top.appendChild(pill);
      }

      const pathEl = document.createElement('div');
      pathEl.className = 'mono';
      pathEl.style.fontSize = '0.73rem';
      pathEl.style.color = COLOR_MUTED;
      pathEl.textContent = bl.source_path;

      card.appendChild(top);
      card.appendChild(pathEl);

      if (bl.snippet) {
        const snip = document.createElement('div');
        snip.className = 'backlink-snippet';
        snip.textContent = bl.snippet;
        card.appendChild(snip);
      }
      list.appendChild(card);
    });
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
      k.className = CLS_BADGE_ACCENT;
      k.textContent = doc.kind;
      badges.appendChild(k);
    }
    if (doc.archived) {
      const a = document.createElement('span');
      a.className = CLS_BADGE_WARN;
      a.textContent = 'archived';
      badges.appendChild(a);
    }

    renderMetadataBadges(doc.badges, doc.sources);
    renderDecisionChain(doc.decision_chain);

    const rendered = document.getElementById('docRenderedBody');
    rendered.innerHTML = doc.html || '';
    document.getElementById('docRawBody').textContent = doc.raw || '';
    applyDocViewMode();

    renderBacklinks(doc);
  }

  async function loadFile(relPath, scrollToStart = true) {
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
        if (activeFilePath !== relPath) return;
        showToast(err.error || 'Failed to open file', 'error');
        if (res.status === 404) {
          showOverviewView();
        }
        return;
      }
      const doc = await res.json();
      if (activeFilePath !== relPath) return;
      showDocumentView(doc);
      if (scrollToStart) globalThis.scrollTo(0, 0);
    } catch {
      if (activeFilePath === relPath) showToast('Failed to load file', 'error');
    }
  }

  function decorateOrphanGroup(groupEl, orphanInfo) {
    const headerBtn = groupEl.firstElementChild;
    if (!headerBtn) return;

    const row = document.createElement('div');
    row.className = 'tree-row-with-actions';
    groupEl.insertBefore(row, headerBtn);
    row.appendChild(headerBtn);

    const badge = document.createElement('span');
    badge.className = CLS_BADGE_DANGER + ' mini-badge';
    badge.textContent = 'Orphaned';
    badge.title = 'Root directory missing: ' + (orphanInfo.root || '');

    const pruneBtn = document.createElement('button');
    pruneBtn.type = 'button';
    pruneBtn.className = 'mini-prune-btn';
    pruneBtn.textContent = 'Prune';
    pruneBtn.title = 'Delete orphaned staging directory';
    pruneBtn.onclick = function (ev) {
      ev.stopPropagation();
      openPruneModal(orphanInfo);
    };

    row.appendChild(badge);
    row.appendChild(pruneBtn);
  }

  async function refreshOrphans() {
    try {
      const res = await fetch('/api/gc');
      if (!res.ok) return;
      const data = await res.json();
      currentOrphans = data.orphans || [];

      const pill = document.getElementById('orphanHeaderBtn');
      const countEl = document.getElementById('orphanHeaderCount');
      if (pill && countEl) {
        countEl.textContent = String(currentOrphans.length);
        if (currentOrphans.length > 0) pill.classList.remove('hidden');
        else pill.classList.add('hidden');
      }
      if (document.getElementById('orphansModal').classList.contains('open')) {
        renderOrphansList();
      }
    } catch {
      // Ignore transient polling failures; manual refresh or next SSE event retries.
    }
  }

  function openOrphansModal() {
    renderOrphansList();
    document.getElementById('orphansModal').classList.add('open');
  }

  function closeOrphansModal() {
    document.getElementById('orphansModal').classList.remove('open');
  }

  function renderOrphansList() {
    const list = document.getElementById('orphansModalList');
    if (!list) return;
    list.innerHTML = '';

    if (currentOrphans.length === 0) {
      const empty = document.createElement('div');
      empty.className = CLS_EMPTY_NOTE;
      empty.textContent = 'No orphaned clones or pinned workspaces detected.';
      list.appendChild(empty);
      return;
    }

    currentOrphans.forEach(function (item) {
      const card = document.createElement('div');
      card.className = 'orphan-card';

      const info = document.createElement('div');
      info.className = 'orphan-card-info';

      const top = document.createElement('div');
      top.style.display = 'flex';
      top.style.alignItems = 'center';
      top.style.gap = '6px';
      const badge = document.createElement('span');
      badge.className = CLS_BADGE_DANGER;
      badge.textContent = item.scope;
      const pathEl = document.createElement('strong');
      pathEl.className = 'mono';
      pathEl.textContent = item.rel_path;
      top.appendChild(badge);
      top.appendChild(pathEl);

      const rootLine = document.createElement('div');
      rootLine.className = 'mono';
      rootLine.style.color = COLOR_MUTED;
      rootLine.style.marginTop = '4px';
      rootLine.textContent = 'Missing root: ' + item.root;

      info.appendChild(top);
      info.appendChild(rootLine);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'danger';
      btn.textContent = 'Prune...';
      btn.onclick = function () { openPruneModal(item); };

      card.appendChild(info);
      card.appendChild(btn);
      list.appendChild(card);
    });
  }

  function openPruneModal(orphanInfo) {
    pendingPruneTarget = orphanInfo;
    document.getElementById('pruneMissingRoot').textContent = orphanInfo.root || '-';
    document.getElementById('pruneTargetRel').textContent = orphanInfo.rel_path || '-';
    const wikiNote = document.getElementById('pruneWikiNote');
    if (orphanInfo.scope === 'clone') wikiNote.classList.remove('hidden');
    else wikiNote.classList.add('hidden');
    const errBox = document.getElementById('pruneErrorBox');
    errBox.classList.add('hidden');
    errBox.textContent = '';
    document.getElementById('pruneConfirmBtn').disabled = false;
    document.getElementById('pruneModal').classList.add('open');
  }

  function closePruneModal() {
    pendingPruneTarget = null;
    document.getElementById('pruneModal').classList.remove('open');
  }

  async function confirmPruneOrphan() {
    if (!pendingPruneTarget || !pendingPruneTarget.rel_path) return;
    const targetPath = pendingPruneTarget.rel_path;
    const btn = document.getElementById('pruneConfirmBtn');
    const errBox = document.getElementById('pruneErrorBox');
    btn.disabled = true;
    errBox.classList.add('hidden');

    try {
      const res = await fetch('/api/gc/prune', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: targetPath, confirm: true })
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        errBox.textContent = data.error || 'Failed to prune orphaned directory';
        errBox.classList.remove('hidden');
        btn.disabled = false;
        return;
      }

      closePruneModal();
      if (activeFilePath && activeFilePath.startsWith(targetPath + '/')) {
        clearSelection();
      }
      showToast('Pruned ' + targetPath, 'success');
      await refreshAll();
    } catch {
      errBox.textContent = 'Request failed';
      errBox.classList.remove('hidden');
      btn.disabled = false;
    }
  }

  function openSearchModal() {
    const modal = document.getElementById('searchModal');
    modal.classList.add('open');
    const input = document.getElementById('searchInput');
    if (input) {
      input.focus();
      input.select();
    }
    runSearch();
  }

  function closeSearchModal() {
    document.getElementById('searchModal').classList.remove('open');
  }

  function setSearchScope(scope) {
    searchScopeFilter = scope;
    document.querySelectorAll('#searchModal .filter-pill[data-scope]').forEach(function (el) {
      if (el.getAttribute('data-scope') === scope) el.classList.add('active');
      else el.classList.remove('active');
    });
    runSearch();
  }

  function setSearchType(docType) {
    searchTypeFilter = docType;
    document.querySelectorAll('#searchModal .filter-pill[data-type]').forEach(function (el) {
      if (el.getAttribute('data-type') === docType) el.classList.add('active');
      else el.classList.remove('active');
    });
    runSearch();
  }

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 90);
  }

  function onSearchKeyDown(ev) {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      closeSearchModal();
      return;
    }
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      if (searchResultsList.length > 0) {
        searchSelectedIdx = (searchSelectedIdx + 1) % searchResultsList.length;
        renderSearchResults();
      }
      return;
    }
    if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      if (searchResultsList.length > 0) {
        searchSelectedIdx = (searchSelectedIdx - 1 + searchResultsList.length) % searchResultsList.length;
        renderSearchResults();
      }
      return;
    }
    if (ev.key === 'Enter' && searchResultsList[searchSelectedIdx]) {
      ev.preventDefault();
      closeSearchModal();
      navigateToFile(searchResultsList[searchSelectedIdx].path);
    }
  }

  async function runSearch() {
    const input = document.getElementById('searchInput');
    const q = input ? input.value.trim() : '';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (searchScopeFilter) params.set('scope', searchScopeFilter);
    if (searchTypeFilter) params.set('type', searchTypeFilter);
    params.set('limit', '40');

    try {
      const res = await fetch('/api/search?' + params.toString());
      if (!res.ok) return;
      const data = await res.json();
      searchResultsList = data.results || [];
      searchSelectedIdx = 0;
      renderSearchResults();
    } catch {
      // Ignore transient search fetch failures while typing.
    }
  }

  function findNextHighlightMatch(lower, tokens, cursor) {
    let bestIdx = -1;
    let bestLen = 0;
    for (const tok of tokens) {
      if (!tok) continue;
      const found = lower.indexOf(tok, cursor);
      if (found >= 0 && (bestIdx < 0 || found < bestIdx)) {
        bestIdx = found;
        bestLen = tok.length;
      }
    }
    return { bestIdx: bestIdx, bestLen: bestLen };
  }

  function appendHighlightedText(parent, text, tokens) {
    if (!text) return;
    if (!tokens || tokens.length === 0) {
      parent.appendChild(document.createTextNode(text));
      return;
    }
    const lower = text.toLowerCase();
    let cursor = 0;
    while (cursor < text.length) {
      const match = findNextHighlightMatch(lower, tokens, cursor);
      if (match.bestIdx < 0) {
        parent.appendChild(document.createTextNode(text.slice(cursor)));
        break;
      }
      if (match.bestIdx > cursor) {
        parent.appendChild(document.createTextNode(text.slice(cursor, match.bestIdx)));
      }
      const mark = document.createElement('mark');
      mark.textContent = text.slice(match.bestIdx, match.bestIdx + match.bestLen);
      parent.appendChild(mark);
      cursor = match.bestIdx + match.bestLen;
    }
  }

  function renderSearchResults() {
    const container = document.getElementById('searchResults');
    if (!container) return;
    container.innerHTML = '';

    if (searchResultsList.length === 0) {
      const empty = document.createElement('div');
      empty.className = CLS_EMPTY_NOTE;
      empty.style.padding = '12px 4px';
      empty.textContent = 'No matching fragments or wiki pages found.';
      container.appendChild(empty);
      return;
    }

    const input = document.getElementById('searchInput');
    const tokens = (input ? input.value : '').trim().toLowerCase().split(/\s+/).filter(Boolean);

    searchResultsList.forEach(function (item, idx) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'search-result-item' + (idx === searchSelectedIdx ? ' selected' : '');
      btn.onclick = function () {
        closeSearchModal();
        navigateToFile(item.path);
      };

      const top = document.createElement('div');
      top.className = 'search-result-top';

      const title = document.createElement('span');
      title.className = 'search-result-title';
      title.textContent = item.title || item.name;

      const badges = document.createElement('span');
      badges.className = 'search-result-badges';

      const scopeBadge = document.createElement('span');
      scopeBadge.className = 'badge';
      scopeBadge.textContent = item.scope;
      badges.appendChild(scopeBadge);

      const typeBadge = document.createElement('span');
      typeBadge.className = CLS_BADGE_ACCENT;
      typeBadge.textContent = item.type;
      badges.appendChild(typeBadge);

      if (item.archived) {
        const archBadge = document.createElement('span');
        archBadge.className = CLS_BADGE_WARN;
        archBadge.textContent = 'archived';
        badges.appendChild(archBadge);
      }

      top.appendChild(title);
      top.appendChild(badges);

      const pathEl = document.createElement('div');
      pathEl.className = 'search-result-path mono';
      pathEl.textContent = item.path;

      btn.appendChild(top);
      btn.appendChild(pathEl);

      if (item.snippet) {
        const snip = document.createElement('div');
        snip.className = 'search-result-snippet';
        appendHighlightedText(snip, item.snippet, tokens);
        btn.appendChild(snip);
      }

      container.appendChild(btn);
    });
  }

  function onModalBackdropClick(ev, modalId) {
    if (ev.target && ev.target.id === modalId) {
      document.getElementById(modalId).classList.remove('open');
    }
  }

  function bindModalBackdrops() {
    ['searchModal', 'orphansModal', 'pruneModal'].forEach(function (modalId) {
      const el = document.getElementById(modalId);
      if (el) {
        el.addEventListener('click', function (ev) { onModalBackdropClick(ev, modalId); });
      }
    });
  }

  async function refreshAll() {
    await Promise.all([refreshTree(), refreshOrphans()]);
    if (activeFilePath) {
      await loadFile(activeFilePath, false);
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
      } catch {
        // Fall back to default change marker when payload is non-JSON.
      }
      recordEventRow(ev);
      refreshAll();
      changeListeners.forEach(function (fn) {
        try {
          fn(ev);
        } catch {
          // Isolate subscriber errors so other listeners continue firing.
        }
      });
    });

    eventSource.onerror = function () {
      setSSEStatus('error', 'Reconnecting...');
    };
  }

  globalThis.addEventListener('hashchange', function () {
    const target = parseHashFile();
    if (target) loadFile(target);
    else {
      activeFilePath = '';
      showOverviewView();
      renderTree();
    }
  });

  globalThis.applyTheme = applyTheme;
  globalThis.refreshAll = refreshAll;
  globalThis.clearEventLog = clearEventLog;
  globalThis.clearSelection = clearSelection;
  globalThis.setAllExpanded = setAllExpanded;
  globalThis.navigateToFile = navigateToFile;
  globalThis.toggleDocViewMode = toggleDocViewMode;
  globalThis.openSearchModal = openSearchModal;
  globalThis.closeSearchModal = closeSearchModal;
  globalThis.setSearchScope = setSearchScope;
  globalThis.setSearchType = setSearchType;
  globalThis.onSearchInput = onSearchInput;
  globalThis.onSearchKeyDown = onSearchKeyDown;
  globalThis.openOrphansModal = openOrphansModal;
  globalThis.closeOrphansModal = closeOrphansModal;
  globalThis.openPruneModal = openPruneModal;
  globalThis.closePruneModal = closePruneModal;
  globalThis.confirmPruneOrphan = confirmPruneOrphan;
  globalThis.onModalBackdropClick = onModalBackdropClick;

  document.addEventListener('keydown', function (ev) {
    if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
      ev.preventDefault();
      if (document.getElementById('searchModal').classList.contains('open')) {
        closeSearchModal();
      } else {
        openSearchModal();
      }
      return;
    }
    if (ev.key === 'Escape') {
      closeSearchModal();
      closePruneModal();
      closeOrphansModal();
    }
  });

  (function setShortcutLabel() {
    const kbd = document.getElementById('searchShortcutKey');
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.userAgent || '';
    if (kbd && platform && !platform.toLowerCase().includes('mac')) {
      kbd.textContent = 'Ctrl+K';
    }
  })();

  document.addEventListener('click', function (ev) {
    const link = ev.target && ev.target.closest ? ev.target.closest('a.wikilink') : null;
    if (!link) return;
    const targetPath = link.getAttribute('data-path');
    if (targetPath) {
      ev.preventDefault();
      navigateToFile(targetPath);
    }
  });
  globalThis.memoirEvents = {
    onStoreChange: function (fn) {
      changeListeners.add(fn);
      return function () { changeListeners.delete(fn); };
    }
  };

  initTheme();
  initSidebarResize();
  bindModalBackdrops();
  connectSSE();
  Promise.all([refreshTree(), refreshOrphans()]).then(function () {
    const initial = parseHashFile();
    if (initial) {
      loadFile(initial);
    }
  });
})();
