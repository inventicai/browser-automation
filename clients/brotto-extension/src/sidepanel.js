// sidepanel.js — chat UI rewrite for the Brotto side panel.
// Preserves all event handlers, state machine, and message listeners.
// Only rendering functions are updated to produce the Claude-in-Chrome chat interface.

const messagesEl  = document.getElementById('messages');
const emptyState   = document.getElementById('emptyState');
const goalEl       = document.getElementById('goal');
const sendBtn      = document.getElementById('sendBtn');
const stopBtn      = document.getElementById('stopBtn');
const workingInd   = document.getElementById('workingIndicator');
const settingsBtn  = document.getElementById('settingsBtn');
const settingsOverlay = document.getElementById('settingsOverlay');
const settingsPanel   = document.getElementById('settingsPanel');
const settingsClose   = document.getElementById('settingsClose');
const plannerUrlSetting = document.getElementById('plannerUrlSetting');

// Preserved DOM IDs for background.ts compatibility
const plannerUrlEl    = document.getElementById('plannerUrl');
const startingUrlEl   = document.getElementById('startingUrl');
const connectBtn      = document.getElementById('connectBtn');
const disconnectBtn   = document.getElementById('disconnectBtn');
const refreshBtn      = document.getElementById('refreshBtn');
const brandDot        = document.getElementById('brandDot');
const stepCountEl     = document.getElementById('stepCount');
const timerEl         = document.getElementById('timer');
const statusBarEl     = document.getElementById('statusBar');
const stepCountActive = document.getElementById('stepCountActive');
const timerActiveEl   = document.getElementById('timerActive');
const newTaskBtn      = document.getElementById('newTaskBtn');
const connectionMeta  = document.getElementById('connectionMeta');
const statusPill      = document.getElementById('statusPill');
// ponytail: tab-bar handles — render each lifecycle event (open/close/nav/
// focus) as a row so the user sees what the agent touched in their browser.
const tabBar         = document.getElementById('tabBar');
const tabBarBody     = document.getElementById('tabBarBody');
const tabBarToggle   = document.getElementById('tabBarToggle');

// ponytail: soft length cap on user task input. Tasks over this many chars
// trigger a confirm() before send; matching server warning at the same
// threshold (defense in depth). Not a hard block — the user is the
// final authority on what they want the agent to do.
const MAX_TASK_CHARS = 1000;

// ── Settings panel ────────────────────────────────────────────────────────
// (handlers below — reads chrome.storage.local, writes on Save)

// ponytail: tab-bar — collapsed/expanded by default. Each row shows badge
// (kind), title (or url), and a one-line context line.
const seenTabs = new Map(); // tabId → {kind, url, title, lastUpdate}
let tabBarCollapsed = false;
function renderTabBar() {
  // ponytail: tab bar is hidden — the new TABS status cell handles the
  // count, and the tab lifecycle rows were noisy (badge + title + URL +
  // tab id, with the badge floating outside the pill). We keep the
  // function around so the tab lifecycle still feeds the cell, but the
  // panel itself is no longer rendered.
  if (tabBar) tabBar.hidden = true;
  return;
  tabBarBody.replaceChildren();
  if (seenTabs.size === 0) {
    const empty = document.createElement('div');
    empty.className = 'tab-row-empty';
    empty.textContent = 'No tabs opened by the agent.';
    tabBarBody.appendChild(empty);
    return;
  }
  // ponytail: render in event order; we keep insertion order via Map. Most
  // recent row at the bottom by appending as we iterate.
  for (const [, row] of seenTabs) {
    const row_el = document.createElement('div');
    row_el.className = 'tab-row';
    const badge = document.createElement('span');
    badge.className = 'tab-row-badge ' + row.kind;
    badge.textContent = row.kind;
    row_el.appendChild(badge);
    const info = document.createElement('div');
    info.className = 'tab-row-info';
    const titleEl = document.createElement('div');
    titleEl.className = 'tab-row-title';
    titleEl.textContent = row.title || row.url || '(no title)';
    titleEl.title = row.title || row.url || '';
    info.appendChild(titleEl);
    const urlEl = document.createElement('div');
    urlEl.className = 'tab-row-url';
    urlEl.textContent = row.url || '—';
    urlEl.title = row.url || '';
    info.appendChild(urlEl);
    row_el.appendChild(info);
    tabBarBody.appendChild(row_el);
  }
  // tabBar.hidden = false removed — the new TABS status cell owns the count.
  // The lifecycle rows are still built (so the data path stays intact for
  // any future debug tool) but the panel itself never renders.
}
function recordTabEvent(ev) {
  if (!ev) return;
  // ponytail: "closed" removes the row; everything else updates in place.
  if (ev.kind === 'closed') {
    seenTabs.delete(ev.tabId);
  } else {
    seenTabs.set(ev.tabId, { tabId: ev.tabId, kind: ev.kind, url: ev.url, title: ev.title });
  }
  renderTabBar();
  updateTabCount();
}
function updateTabCount() {
  const cell = document.getElementById('tabCountCell');
  const value = document.getElementById('tabCountActive');
  if (!cell || !value) return;
  const n = seenTabs.size;
  value.textContent = String(n);
  // Hide the cell when zero — empty stats are noise.
  cell.hidden = n === 0;
}

// ponytail: context utilization cell — backend is the source of truth.
// The harness emits `{tokens, window, pct}` per step (pct is the actual
// model-reported usage / model's context window). The frontend just
// renders the latest values stored on state. The `/context` endpoint
// fetches the model's window on init so the baseline is right before
// any step arrives.
function updateContextUsage() {
  const cell = document.getElementById('contextCell');
  const value = document.getElementById('contextValue');
  if (!cell || !value) return;
  const { tokens, window, pct } = state.lastContext || {};
  if (tokens == null || pct == null) {
    value.textContent = '0%';
    value.title = window
      ? `${window.toLocaleString()} tokens window`
      : 'no context yet';
    cell.hidden = false;
    return;
  }
  // ponytail: backend emits pct to one decimal. Drop trailing zeros
  // so 25.0 → "25%", 12.5 → "12.5%", 2.5 → "2.5%".
  const displayPct = +pct.toFixed(1);
  value.textContent = `${displayPct}%`;
  value.title = `${tokens.toLocaleString()} / ${window.toLocaleString()} tokens (${pct}%)`;
  cell.hidden = false;
}

// ponytail: ask the SW to fetch the model's context window from the
// backend. The SW proxies through the configured serverUrl so we don't
// duplicate that config on the sidepanel. Cached on state.contextWindow
// after the first hit; called on init and on connect.
async function fetchContextWindow() {
  try {
    const res = await sendMessage({ type: 'get_context' });
    if (!res || !res.success || !res.context) return;
    const { window } = res.context;
    if (typeof window !== 'number') return;
    state.contextWindow = window;
    state.contextModel = res.context.model;
    if (!state.lastContext) state.lastContext = { tokens: null, window, pct: null };
    else state.lastContext.window = window;
    updateContextUsage();
  } catch { /* offline / not running — backend will fill it in */ }
}
if (tabBarToggle) {
  tabBarToggle.addEventListener('click', () => {
    tabBarCollapsed = !tabBarCollapsed;
    tabBar.classList.toggle('collapsed', tabBarCollapsed);
    tabBarToggle.textContent = tabBarCollapsed ? '+' : '−';
    tabBarToggle.setAttribute('aria-expanded', String(!tabBarCollapsed));
  });
}
settingsClose.addEventListener('click', () => settingsOverlay.classList.remove('open'));
settingsOverlay.addEventListener('click', (e) => {
  if (e.target === settingsOverlay) settingsOverlay.classList.remove('open');
});
plannerUrlSetting.addEventListener('input', () => {
  plannerUrlEl.value = plannerUrlSetting.value;
});

// ── Settings: load + save (first chrome.storage.local writes — today the
// SW only reads `get("settings")`, so this is the seed for that key).
const securityModeSetting = document.getElementById('securityModeSetting');
const blacklistSetting    = document.getElementById('blacklistSetting');
const floorBlacklistEl    = document.getElementById('floorBlacklist');
const saveSettingsBtn     = document.getElementById('saveSettingsBtn');
const refreshPolicyBtn    = document.getElementById('refreshPolicyBtn');

// ponytail: on Settings open, fetch the EFFECTIVE policy from the server
// so the sidepanel shows what the server is actually enforcing (floor +
// user merged), not the user's local cache. The user's saved edits still
// drive the editable textarea; the floor is rendered read-only above it.
settingsBtn.addEventListener('click', async () => {
  plannerUrlSetting.value = plannerUrlEl.value || 'http://localhost:8000';
  await hydrateSettingsPanel();
  settingsOverlay.classList.add('open');
  renderVerifyStatus();
});

// ponytail: Q1 — extracted so the Refresh button can re-run the same
// fetch + render flow without re-opening the panel.
async function hydrateSettingsPanel() {
  // ponytail: chrome.storage.local is the AUTHORITATIVE source for what
  // the SW will ship on the next task_start. The server's /v1/policy
  // view is only used to render the org-floor (locked) list — it must
  // NOT override the user's locally-saved mode/blacklist, or the UI
  // lies about what's actually enforced. Without this, a user could
  // think they're in normal mode while the SW still ships yesterday's
  // secure+blacklist saved in storage.
  const stored = await chrome.storage.local.get('settings');
  const s = stored.settings || {};
  const base = (plannerUrlEl.value || 'http://localhost:8000').replace(/\/$/, '');

  // Fetch server's effective policy in parallel with reading local cache.
  let effective = null;
  try {
    const r = await fetch(`${base}/v1/policy`);
    if (r.ok) effective = await r.json();
    console.log('[brotto] policy from server:', effective);
  } catch (e) {
    console.warn('[brotto] could not fetch /v1/policy, using local cache:', e);
  }
  // Cache the fetched effective policy so the Save handler can read the
  // floor list from it (we don't want to re-fetch on every Save).
  state.lastEffective = effective;
  // Track when we last successfully verified policy with the server.
  // Used to render a "Last verified N seconds ago" footer so the user
  // knows whether the sidepanel is grounded in fresh server state or
  // showing stale local data.
  state.lastVerifiedAt = effective ? Date.now() : (state.lastVerifiedAt || null);
  state.serverReachable = !!effective;

  // Mode + blacklist come from LOCAL storage. The server view is used
  // only to display the locked floor list — it never overrides the
  // user's saved settings here.
  const mode = s.mode === 'secure' ? 'secure' : 'normal';
  securityModeSetting.value = mode;
  const localBlacklist = Array.isArray(s.blacklist) ? s.blacklist : [];

  // Floor (locked) — always rendered from the server when available.
  // Build via DOM APIs (not innerHTML) so a malicious floor file can't
  // smuggle markup into the sidepanel.
  const floorList = Array.isArray(effective?.source?.floor) ? effective.source.floor : [];
  if (floorBlacklistEl) {
    while (floorBlacklistEl.firstChild) floorBlacklistEl.removeChild(floorBlacklistEl.firstChild);
    if (!effective) {
      // ponytail: Bug 6 — server unreachable. Don't pretend there are
      // no org entries. Be explicit so the user knows their saved list
      // is shown below but the org floor is unknown right now.
      const empty = document.createElement('div');
      empty.className = 'floor-empty floor-unreachable';
      empty.textContent =
        '⚠ Could not reach server — organisation policy list unknown. ' +
        'Your saved entries below are still active locally.';
      floorBlacklistEl.appendChild(empty);
    } else if (floorList.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'floor-empty';
      empty.textContent = 'No organisation-wide entries.';
      floorBlacklistEl.appendChild(empty);
    } else {
      for (const d of floorList) {
        const row = document.createElement('div');
        row.className = 'floor-item';
        const lock = document.createTextNode('🔒 ');
        const name = document.createTextNode(d + ' ');
        const tag = document.createElement('span');
        tag.className = 'floor-tag';
        tag.textContent = 'organisation policy';
        row.appendChild(lock);
        row.appendChild(name);
        row.appendChild(tag);
        floorBlacklistEl.appendChild(row);
      }
    }
  }

  // ponytail: textarea shows user-ONLY entries (the local blacklist
  // minus the floor). The floor is locked above; the user can't "edit"
  // a locked entry by deleting it — on Save we re-union and persist.
  const userOnly = localBlacklist.filter((d) => !floorList.includes(d));
  blacklistSetting.value = userOnly.join('\n');

  // Header line: how many domains the user has saved (local view).
  // Floor is rendered separately above; this count matches what the SW
  // will actually ship on the next task_start.
  const headerEl = document.getElementById('policyModeHeader');
  if (headerEl) {
    if (mode === 'secure') {
      headerEl.textContent = `Mode: secure · ${localBlacklist.length} domain${localBlacklist.length === 1 ? '' : 's'} saved locally.`;
      headerEl.classList.add('secure');
    } else {
      headerEl.textContent = 'Mode: normal — secure mode not active.';
      headerEl.classList.remove('secure');
    }
  }
}

// ponytail: Q1 — refresh from server without re-opening Settings.
// Re-runs the same hydration flow so the user sees the latest
// effective policy without a full panel reopen.
if (refreshPolicyBtn) {
  refreshPolicyBtn.addEventListener('click', async () => {
    refreshPolicyBtn.disabled = true;
    const original = refreshPolicyBtn.textContent;
    refreshPolicyBtn.textContent = '↻ Refreshing…';
    try {
      await hydrateSettingsPanel();
      renderVerifyStatus();
      refreshPolicyBtn.textContent = '✓ Refreshed';
    } catch {
      refreshPolicyBtn.textContent = '⚠ Refresh failed';
    } finally {
      setTimeout(() => {
        refreshPolicyBtn.textContent = original;
        refreshPolicyBtn.disabled = false;
      }, 1500);
    }
  });
}

// ponytail: footer that tells the user whether the sidepanel's policy
// view is grounded in fresh server state, stale, or local-only. Re-render
// on save (server just confirmed) and on every settings open.
function renderVerifyStatus() {
  const el = document.getElementById('settingsVerifyStatus');
  if (!el) return;
  el.classList.remove('ok', 'stale', 'off');
  if (!state.serverReachable) {
    el.classList.add('off');
    el.innerHTML = '';
    const dot = document.createElement('span'); dot.className = 'dot';
    const txt = document.createTextNode('Server unreachable — your edits are saved locally and will sync when it returns.');
    el.appendChild(dot); el.appendChild(txt);
    return;
  }
  if (!state.lastVerifiedAt) {
    el.classList.add('stale');
    el.textContent = 'Verifying server…';
    return;
  }
  const ageSec = Math.max(0, Math.round((Date.now() - state.lastVerifiedAt) / 1000));
  const ageLabel = ageSec < 5 ? 'just now'
    : ageSec < 60 ? `${ageSec}s ago`
    : `${Math.round(ageSec / 60)}m ago`;
  el.classList.add('ok');
  el.innerHTML = '';
  const dot = document.createElement('span'); dot.className = 'dot';
  const txt = document.createTextNode(`Server confirmed · ${ageLabel}`);
  el.appendChild(dot); el.appendChild(txt);
}

if (saveSettingsBtn) {
  saveSettingsBtn.addEventListener('click', async () => {
    // Bug 8: if a task is currently running, the new policy won't take
    // effect until the next task_start. Capture that so we can change
    // the button copy.
    const taskRunning = state.phase === 'executing' || state.phase === 'paused';

    // Read what the user has in their editable list; the floor list is
    // locked and not editable here. On Save we POST only the user portion
    // — the server merges it with the floor on next task_start.
    const userListRaw = blacklistSetting.value.split('\n').map((s) => s.trim()).filter(Boolean);
    // Re-derive the union by pulling the floor from the visible lock list.
    const floorList = Array.isArray(state.lastEffective?.source?.floor) ? state.lastEffective.source.floor : [];
    const merged = Array.from(new Set([...floorList, ...userListRaw]));
    const settings = {
      serverUrl: plannerUrlSetting.value || 'http://localhost:8000',
      mode: securityModeSetting.value === 'secure' ? 'secure' : 'normal',
      blacklist: merged,
    };
    await chrome.storage.local.set({ settings });
    plannerUrlEl.value = settings.serverUrl;
    console.log('[brotto] settings saved', settings);

    // 1. Push the in-memory mirror to the SW so the next task_start
    //    ships it. Bug 7: wait for the SW's success ack so we don't
    //    claim "Saved" before the SW actually updated userPolicy.
    let swOk = false;
    try {
      const ack = await chrome.runtime.sendMessage({
        type: 'policy_changed',
        settings: { mode: settings.mode, blacklist: settings.blacklist },
      });
      swOk = !!(ack && ack.success);
      if (!swOk) console.warn('[brotto] SW ack missing or unsuccessful:', ack);
    } catch (e) {
      console.warn('[brotto] policy_changed message failed (SW asleep):', e);
    }

    // 2. HTTP POST to the server so the audit log records the save even
    //    when no WS is open (i.e. no task running). We surface the
    //    outcome in the button text so the user can see whether the
    //    save actually reached the server (not just local storage).
    saveSettingsBtn.disabled = true;
    saveSettingsBtn.textContent = 'Saving…';
    renderVerifyStatus();
    let serverOk = false;
    try {
      const base = settings.serverUrl.replace(/\/$/, '');
      const r = await fetch(`${base}/v1/policy_ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { mode: settings.mode, blacklist: settings.blacklist } }),
      });
      serverOk = r.ok;
      console.log('[brotto] policy_ack http status', r.status);
    } catch (e) {
      console.warn('[brotto] policy_ack http failed (server may be offline):', e);
    }

    if (swOk && serverOk) {
      // Refresh the verified timestamp so the footer shows "just now".
      state.lastVerifiedAt = Date.now();
      state.serverReachable = true;
      saveSettingsBtn.textContent = taskRunning
        ? '✓ Saved — applies to next task'
        : '✓ Saved — server confirmed';
    } else if (!swOk && serverOk) {
      // Local + server both fine, but the SW didn't ack — suspicious.
      // Still show success but warn the user.
      saveSettingsBtn.textContent = taskRunning
        ? '⚠ Saved — applies to next task (SW did not ack)'
        : '⚠ Saved — SW did not ack (will retry on next task)';
    } else {
      state.serverReachable = false;
      saveSettingsBtn.textContent = '⚠ Saved locally — server unreachable';
    }
    renderVerifyStatus();
    setTimeout(() => {
      saveSettingsBtn.textContent = 'Save';
      saveSettingsBtn.disabled = false;
    }, 2200);
  });
}

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  phase: 'idle',
  plannerUrl: '',
  sessionId: null,
  startTime: 0,
  stepCount: 0,
  pendingClarifyId: null,
};

let timerInterval = null;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ponytail: small helper to create an icon-only button for the final-answer
// toolbar. Glyph is rendered as text (no emoji). Clicked-state styling lives
// in CSS via .clicked.
// ponytail: Lucide icon paths. License: MIT (https://lucide.dev). Each icon
// is a focused 24×24 stroke-based glyph that inherits `currentColor` so
// the .final-answer-icon-btn CSS can recolor on hover / clicked.
const LUCIDE_ICONS = {
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>',
  thumbsUp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7a2 2 0 0 1-2-1.88V11.88a2 2 0 0 1 2-2.12l4.32-4.32A2 2 0 0 1 13 4.83V9a2 2 0 0 0 2 2.88z"/></svg>',
  thumbsDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H17a2 2 0 0 1 2 1.88v8.24a2 2 0 0 1-2 2.12l-4.32 4.32A2 2 0 0 1 11 19.17V15a2 2 0 0 0-2-2.88z"/></svg>',
  retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></svg>',
};

function makeIconBtn(svgContent, title, onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'final-answer-icon-btn';
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.innerHTML = svgContent;
  btn.addEventListener('click', onClick);
  return btn;
}

// ponytail: store feedback (good/bad) per task in localStorage so the
// user has a record of what they rated. The orchestrator can read this
// later if needed.
function recordFeedback(kind) {
  try {
    const stored = JSON.parse(localStorage.getItem('brotto-feedback') || '[]');
    stored.push({
      kind,
      task: state.lastGoal || '',
      timestamp: Date.now(),
    });
    localStorage.setItem('brotto-feedback', JSON.stringify(stored));
  } catch {}
}

// ponytail: re-run the same task under a new session. Resets the chat
// then re-sends the last goal using the same message type the initial
// task uses (run_local_task). The SW does not have a send_user_message
// case, so retry used to silently fail. Mirroring run_local_task also
// guarantees the orchestrator sees a fresh session. The goal must be
// captured BEFORE resetForNewTask — that fn clears state.lastGoal.
function retryLastTask() {
  const goal = state.lastGoal;
  if (!goal) return;
  resetForNewTask();
  void sendMessage({
    type: 'run_local_task',
    task: goal,
    plannerUrl: plannerUrlEl.value || undefined,
    startingUrl: startingUrlEl.value || undefined,
  });
}

// ponytail: clean a URL for chip display. Strips query strings and hash
// (often auth tokens, session IDs — visually noisy and sometimes
// sensitive). Falls back to the raw URL if parsing fails. Truncates
// long paths so the chip stays one line.
function cleanUrl(url, maxLen = 56) {
  if (!url) return '';
  try {
    const u = new URL(url);
    let s = u.hostname + u.pathname;
    if (s.length > maxLen) s = s.slice(0, maxLen - 1) + '…';
    return s;
  } catch {
    return url;
  }
}

// Minimal markdown renderer for agent output.
// HTML-escapes first so injected HTML stays literal; only our own tags get through.
// Block-level: headers, lists, blockquote, hr. Inline: bold, italic, code, links.
function renderMarkdown(raw) {
  if (!raw) return '';
  const esc = escapeHtml(String(raw));
  const lines = esc.split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const trimmed = lines[i].trim();
    // Headers: #, ##, ### (up to ######)
    const h = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (h) {
      const level = h[1].length;
      out.push(`<h${level}>${h[2]}</h${level}>`);
      i++;
      continue;
    }
    // Horizontal rule
    if (/^(-{3,}|_{3,}|\*{3,})\s*$/.test(trimmed)) {
      out.push('<hr>');
      i++;
      continue;
    }
    // Unordered list — group consecutive `- ` / `* ` / `+ ` items
    if (/^[-*+]\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*+]\s+/, ''));
        i++;
      }
      out.push('<ul>' + items.map((it) => `<li>${it}</li>`).join('') + '</ul>');
      continue;
    }
    // Ordered list — group consecutive `1. ` items
    if (/^\d+\.\s+/.test(trimmed)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i++;
      }
      out.push('<ol>' + items.map((it) => `<li>${it}</li>`).join('') + '</ol>');
      continue;
    }
    // Blockquote
    if (/^>\s+/.test(trimmed)) {
      const bq = [];
      while (i < lines.length && /^>\s+/.test(lines[i].trim())) {
        bq.push(lines[i].trim().replace(/^>\s+/, ''));
        i++;
      }
      out.push('<blockquote>' + bq.join('<br>') + '</blockquote>');
      continue;
    }
    // Empty line — paragraph break
    if (trimmed === '') {
      out.push('');
      i++;
      continue;
    }
    // Default: pass the line through (paragraph)
    out.push(lines[i]);
    i++;
  }

  let html = out.join('\n');

  // Inline replacements
  html = html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  html = html.replace(/\*(.+?)\*/g, '<i>$1</i>');
  html = html.replace(/`([^`\n]+)`/g,
    '<code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;font-size:0.88em;font-family:ui-monospace,monospace">$1</code>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

  return html;
}

// ponytail: if the model skipped `reasoning`, derive a sentence from the raw
// action string the local driver produced. Keeps the bubble readable even
// when the model is lazy.
function deriveReasoningFromAction(title, iconKind) {
  const t = (title || '').trim();
  if (!t) return iconKind ? `Working (${iconKind})…` : 'Working on it…';
  if (t.startsWith('visit_url ')) {
    const url = t.slice('visit_url '.length).trim();
    return url ? `Navigating to ${url}…` : 'Navigating…';
  }
  if (t.startsWith('left_click ')) return 'Clicking on the page…';
  if (t.startsWith('double_click ')) return 'Double-clicking…';
  if (t.startsWith('right_click ')) return 'Right-clicking…';
  if (t.startsWith('drag ')) return 'Dragging…';
  if (t.startsWith('scroll ')) return 'Scrolling…';
  if (t.startsWith('key ')) return 'Pressing a key…';
  if (t.startsWith('insert_text ')) {
    const text = t.slice('insert_text '.length).trim();
    return text ? `Typing "${text.slice(0, 40)}${text.length > 40 ? '…' : ''}"…` : 'Typing…';
  }
  if (t.startsWith('history_back')) return 'Going back…';
  if (t.startsWith('screenshot')) return 'Taking a screenshot…';
  if (t.startsWith('wait')) return 'Pausing…';
  if (t.startsWith('memorize_fact')) return 'Storing a note… (legacy: planner should use memoryUpdates now)';
  if (t.startsWith('ask_user_question')) return 'Asking you a question…';
  if (t.startsWith('terminate')) return 'Wrapping up…';
  return t.length > 80 ? `${t.slice(0, 77)}…` : `${t}…`;
}

// ponytail: formatToolCall is no longer used — tool call names are rendered
// inline in the step_card message handler. Kept as a placeholder if the
// tooling needs to expand later. The details panel only shows the names
// (e.g. "navigate, append_scratchpad") when the step had multiple actions.
function formatToolCall(a) {
  if (!a || typeof a.action !== 'string') return '';
  return a.action;
}

// ── SW keep-alive (MV3) ──────────────────────────────────────────────────
// ponytail: open a long-lived port to the service worker so Chrome doesn't
// terminate it between tasks. Without this, the SW is killed after ~30s of
// inactivity, and the next sendMessage can hit a cold-start race — heavy
// imports (CanonicalExtensionController, transport, action-executor) plus
// controller.restore() can take long enough that the message callback
// fires before the SW's onMessage listener is registered. Symptom: the
// second task silently no-ops, side panel stays idle. Reconnect on
// disconnect (SW crash, manual reload from chrome://extensions).
let swKeepAlive = null;
function connectSwKeepAlive() {
  try {
    swKeepAlive = chrome.runtime.connect({ name: "brotto-sidepanel" });
  } catch (err) {
    console.warn("[sidepanel] keep-alive connect failed:", err);
    setTimeout(connectSwKeepAlive, 1000);
    return;
  }
  swKeepAlive.onDisconnect.addListener(() => {
    swKeepAlive = null;
    // ponytail: brief delay so we don't spin if the SW is genuinely gone.
    setTimeout(connectSwKeepAlive, 200);
  });
}
connectSwKeepAlive();

// ── Button handlers (preserved verbatim) ─────────────────────────────────
if (connectBtn) connectBtn.addEventListener('click', () => void connect());
if (disconnectBtn) disconnectBtn.addEventListener('click', () => void disconnect());
if (startBtn) startBtn.addEventListener('click', () => void startTask());
stopBtn.addEventListener('click', () => void stopTask());
if (refreshBtn) refreshBtn.addEventListener('click', () => void refresh());

// ── Input + send ─────────────────────────────────────────────────────────
sendBtn.addEventListener('click', () => void sendUserMessage());
if (newTaskBtn) newTaskBtn.addEventListener('click', () => void resetForNewTask());
goalEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    void sendUserMessage();
  }
});
goalEl.addEventListener('input', () => {
  goalEl.style.height = 'auto';
  goalEl.style.height = Math.min(goalEl.scrollHeight, 120) + 'px';
});

// ponytail: render the CONTEXT cell once on load so the value is owned
// by JS (not just the static HTML default). Then ask the backend for
// the model's context window so the 0% tooltip names the right baseline.
updateContextUsage();
void fetchContextWindow();

async function sendUserMessage() {
  const text = goalEl.value.trim();
  if (!text) return;
  // ponytail: any non-terminal phase means a send is in flight. Guard against
  // double-clicks during the connecting/connected window before the loop sets
  // 'executing'. Without this, two parallel run_local_task messages race and
  // the second hits "A local task is already running" in background.
  if (state.phase !== 'idle' && state.phase !== 'done' && state.phase !== 'error'
      && state.phase !== 'completed' && state.phase !== 'cancelled' && state.phase !== 'disconnected'
      && state.phase !== 'failed' && state.phase !== 'connected') return;
  // ponytail: soft length cap. Tasks > MAX_TASK_CHARS get a confirm dialog
  // because long compound instructions are a classic prompt-injection vector.
  // The server logs a warning on the same threshold (defense in depth) but
  // does not block — both layers are advisory, matching the "do not show by
  // default, prompt the user" UX spec.
  if (text.length > MAX_TASK_CHARS
      && !window.confirm(
        `This task is ${text.length} characters. Long prompts increase the risk of prompt injection. Send anyway?`)) {
    return;
  }
  // ponytail: clear prior conversation so each task starts fresh.
  clearMessages();
  // ponytail: clear previous task's tab-bar (the loop's tabEvent subscriptions
  // are rebounded inside the local-driver for every run_local_task).
  seenTabs.clear();
  if (tabBar) tabBar.hidden = true;
  appendMessage({ role: 'user', text });
  state.lastGoal = text;
  goalEl.value = '';
  goalEl.style.height = 'auto';

  // ponytail: auto-connect on first send. User doesn't need a separate
  // "Connect" step. setPhase('connecting') shows the spinner briefly,
  // then we move to 'connected' and kick off the task.
  setPhase('connecting', `Connecting to ${state.plannerUrl || 'planner'}…`);
  try {
    await ensureConnected();
  } catch (err) {
    setPhase('error', `Connect failed: ${err instanceof Error ? err.message : String(err)}`);
    appendMessage({ role: 'error', text: `Connect failed: ${err instanceof Error ? err.message : String(err)}` });
    return;
  }

  // ponytail: start the timer the moment the user kicks off a task. Earlier
  // wiring only started the timer inside startTask() (bound to a hidden
  // #startBtn), so sendUserMessage's actual run_local_task path never
  // started the counter — the user always saw 0.0s.
  startTimer();
  // ponytail: send the goal to the background. The background opens a
  // new tab, captures observations, calls the planner, dispatches actions
  // via chrome.debugger. The side panel just renders events.
  const response = await sendMessage({ type: 'run_local_task', task: text });
  if (!response.success) {
    stopTimer();
    setPhase('error', `Failed to start: ${response.error || 'unknown error'}`);
    appendMessage({ role: 'error', text: `Failed to start: ${response.error || 'unknown error'}` });
  }
}

async function ensureConnected() {
  // ponytail: reuses the plannerUrl from settings (default :3001). Probes
  // /health; sets phase to 'connected' on success. Throws on failure.
  const url = plannerUrlEl.value.trim() || 'http://localhost:8000';
  state.plannerUrl = url;
  plannerUrlEl.value = url;
  const response = await fetch(url + '/health', { method: 'GET' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  setPhase('connected', null);
  // Status pill in the header already conveys connection state; no
  // separate chat-line clutter.
}

async function resetForNewTask() {
  // ponytail: clear chat stream, reset counters, reset task state.
  // Used by "New task" button and by sendUserMessage to clear before
  // posting a new goal.
  state.lastGoal = '';
  state.stepCount = 0;
  // ponytail: drop the previous task's tab-bar state so each task starts
  // with a fresh journal of what was opened.
  seenTabs.clear();
  renderTabBar();
  if (tabBar) tabBar.hidden = true;
  clearMessages();
  stopTimer();
  setPhase(state.plannerUrl ? 'connected' : 'idle', state.plannerUrl ? 'Ready' : 'Ready');
}

function appendUserMessage(text) {
  appendMessage({ role: 'user', text });
}

// ponytail: tiny logger for internal noise (cancel races, retry ticks)
// that should NOT render in the chat. Service-worker console only via
// console.log inside the page; nothing in the UI changes.
function logSilently(message) {
  console.log(`[sidepanel] ${message}`);
}

// ── Phase / UI helpers ────────────────────────────────────────────────────
function setPhase(phase, message) {
  state.phase = phase;
  const running = phase === 'executing' || phase === 'paused';
  workingInd.classList.toggle('active', running);
  stopBtn.style.display = running ? '' : 'none';
  // ponytail: re-enable the composer explicitly when the task ends so a
  // "done" / "error" / "cancelled" / "disconnected" / "failed" phase
  // always makes the goal input re-usable. setPhase is the single source
  // of truth for the input's enabled state; other code paths must call
  // setPhase rather than toggling sendBtn.disabled directly.
  sendBtn.disabled = running || phase === 'connecting';
  // ponytail: surface a brief feedback message for the prose-only failure
  // so the user knows the loop stopped on purpose, not from a network
  // error. The actual message is rendered by the task_failed handler.
  if (phase === 'done' || phase === 'error') {
    stopTimer();
    // ponytail: clear any lingering login prompt so the bubble + button
    // don't survive into the terminal state. (Auto-resume paths also call
    // clearLoginPrompt directly, so it's idempotent.)
    clearLoginPrompt();
  }
  // ponytail: status pill is visible in the header. Updates text + color
  // class so the user can read connection state at a glance (Idle by default).
  if (connectBtn) connectBtn.disabled = phase === 'connecting' || phase === 'connected' || phase === 'executing';
  if (disconnectBtn) disconnectBtn.disabled = !(phase === 'connected' || phase === 'executing' || phase === 'paused');
  if (startBtn) startBtn.disabled = phase === 'connecting';
  stopBtn.disabled = !(phase === 'executing' || phase === 'paused');
  if (refreshBtn) refreshBtn.disabled = phase === 'connecting';
  // ponytail: status bar (steps + timer) shows during running/paused/done.
  // Hidden in idle/connected/error so the panel stays clean.
  const showBar = phase === 'executing' || phase === 'paused' || phase === 'done';
  if (statusBarEl) statusBarEl.classList.toggle('active', showBar);
  // ponytail: New Task button shows after done or error so the user can
  // start fresh without reloading.
  const showNewTask = phase === 'done' || phase === 'error';
  if (newTaskBtn) newTaskBtn.classList.toggle('visible', showNewTask);
  if (message) connectionMeta.textContent = message;
  // ponytail: Bug 2 — drive the header connection pill from phase.
  // Mid-task disconnects are handled separately via `case 'disconnected'`
  // (Bug 3) which uses setConnPill directly.
  if (phase === 'connected' || phase === 'executing' || phase === 'paused' || phase === 'done') {
    setConnPill('connected', 'Connected');
  } else if (phase === 'connecting') {
    setConnPill(null, 'Connecting…');
  } else if (phase === 'error') {
    setConnPill('error', 'Disconnected');
  } else {
    setConnPill(null, 'Idle');
  }
}

function clearTimer() {
  if (timerInterval !== null) { clearInterval(timerInterval); timerInterval = null; }
  state.startTime = 0;
  timerEl.textContent = '0.0s';
  if (timerActiveEl) timerActiveEl.textContent = '0.0s';
}

function startTimer() {
  clearTimer();
  state.startTime = Date.now();
  timerInterval = setInterval(() => {
    const elapsed = ((Date.now() - state.startTime) / 1000).toFixed(1) + 's';
    if (timerEl) timerEl.textContent = elapsed;
    if (timerActiveEl) timerActiveEl.textContent = elapsed;
  }, 100);
}

function stopTimer() {
  if (timerInterval !== null) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  // ponytail: write the final time to BOTH elements every call. Earlier code
  // only updated the hidden header timer and skipped the visible status bar
  // on stopTimer, so the user kept seeing the last interval value rather than
  // the locked final time. Idempotent — safe to call after the interval is
  // already cleared.
  if (state.startTime > 0) {
    const finalElapsed = ((Date.now() - state.startTime) / 1000).toFixed(1) + 's';
    if (timerEl) timerEl.textContent = finalElapsed;
    if (timerActiveEl) timerActiveEl.textContent = finalElapsed;
  }
}

function updateStepCount() {
  const label = state.stepCount + (state.stepCount === 1 ? ' step' : ' steps');
  stepCountEl.textContent = label;
  if (stepCountActive) stepCountActive.textContent = String(state.stepCount);
}

function clearMessages() {
  messagesEl.replaceChildren();
  state.stepCount = 0;
  updateStepCount();
  stopTimer();
  // ponytail: reset to initial empty-state by adding the empty-state
  // placeholder back so the panel doesn't look empty.
  if (!document.getElementById('emptyState')) {
    const empty = document.createElement('div');
    empty.id = 'emptyState';
    empty.className = 'empty-state';
    empty.innerHTML =
      '<div class="empty-mark"><img src="assets/logo.svg" alt="Inventic" class="brand-logo brand-logo--lg"></div>' +
      '<div class="empty-title">Brotto</div>' +
      '<div class="empty-sub">Describe what you\'d like to do in your browser and Brotto will get it done for you.</div>';
    messagesEl.appendChild(empty);
  }
}

// ── Core logic (preserved verbatim) ───────────────────────────────────────
async function connect() {
  const url = plannerUrlEl.value.trim() || 'http://localhost:8000';
  setPhase('connecting', `Probing ${url}...`);
  try {
    const response = await fetch(url + '/health', { method: 'GET' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const info = await response.json();
    state.plannerUrl = url;
    plannerUrlEl.value = url;
    setPhase('connected', null);
    // Status pill already shows connection; no chat line.
  } catch (err) {
    state.plannerUrl = '';
    setPhase('error', `Connect failed: ${err instanceof Error ? err.message : String(err)}`);
    appendMessage({ role: 'error', text: `Connect failed: ${err instanceof Error ? err.message : String(err)}` });
  }
}

function disconnect() {
  if (state.phase === 'executing' || state.phase === 'paused') void stopTask();
  state.plannerUrl = '';
  setPhase('idle', 'Disconnected');
  appendMessage({ role: 'system', text: 'Disconnected' });
}

// ponytail: Bug 2 — visible connection indicator. Dot-only — state
// conveyed by colour (green/amber/red) + the title-attribute tooltip.
// Driven by WS lifecycle events from background.ts.
function setConnPill(stateName, tooltipLabel) {
  if (!statusPill) return;
  statusPill.classList.remove('connected', 'reconnecting', 'error');
  if (stateName) statusPill.classList.add(stateName);
  // The visible dot only changes colour. The label is in the tooltip
  // (hover / screen-reader / aria-live).
  statusPill.title = `Connection: ${tooltipLabel}`;
}

async function startTask() {
  if (state.phase === 'executing' || state.phase === 'paused') return;
  const goal = goalEl.value.trim();
  if (!goal) {
    appendMessage({ role: 'error', text: 'Enter a task description first.' });
    return;
  }
  if (!state.plannerUrl) {
    await connect();
    if (state.phase !== 'connected') return;
  }
  clearMessages();
  state.sessionId = 'session-' + Date.now();
  setPhase('executing', 'Starting...');
  startTimer();
  appendMessage({ role: 'system', text: `Starting task: ${goal.slice(0, 80)}${goal.length > 80 ? '…' : ''}` });
  const message = { type: 'run_local_task', task: goal, sessionId: state.sessionId };
  const startUrl = startingUrlEl.value.trim();
  const plannerUrl = plannerUrlEl.value.trim();
  if (startUrl) message.startingUrl = startUrl;
  if (plannerUrl) message.plannerUrl = plannerUrl;
  const response = await sendMessage(message);
  if (!response.success) {
    stopTimer();
    setPhase('error', `Start failed: ${response.error || 'unknown'}`);
    appendMessage({ role: 'error', text: `Failed to start: ${response.error || 'unknown error'}` });
  }
}

async function stopTask() {
  // ponytail: guard against double-click. The cancel handler may finish
  // before the user releases the button, and a second click would post
  // 'cancel_local_task' which then returns 'No local task is running'.
  if (state.phase !== 'executing' && state.phase !== 'paused') return;
  stopBtn.disabled = true;
  // ponytail: surface immediate "Stopped" feedback so the user sees their
  // click took effect. The background's cancel emits a terminal event
  // synchronously now, so the side panel exits 'Working' within ~1 tick.
  appendMessage({ role: 'system', text: 'Stopped by user — finishing current step…' });
  setPhase('paused', 'Stopping…');
  const response = await sendMessage({ type: 'cancel_local_task' });
  if (!response.success) {
    // ponytail: cancel after the loop already terminated (the user's
    // second click). The terminal event is already on the way; do not
    // show an error bubble that contradicts it.
    logSilently(`cancel_local_task returned: ${response.error || 'unknown'}`);
  }
}

async function refresh() {
  stopTimer();
  clearMessages();
  const response = await sendMessage({ type: 'reset_session' });
  if (!response.success) appendMessage({ role: 'error', text: `Reset failed: ${response.error || 'unknown error'}` });
  state.plannerUrl = '';
  setPhase('idle', 'Ready');
}

// ── Message sender (preserved verbatim) ────────────────────────────────────
function sendMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      const err = chrome.runtime.lastError;
      resolve(err ? { success: false, error: err.message } : response || { success: false, error: 'No response' });
    });
  });
}

// ── Chat rendering ────────────────────────────────────────────────────────
// ponytail: a single clearMessages is enough — the previous second
// declaration (lines 456-461 in the old file) shadowed this one and skipped
// the empty-state placeholder + timer reset, leaving the panel blank after
// the first task ended. Keep this implementation canonical; remove any
// duplicate.
function clearMessages() {
  messagesEl.replaceChildren();
  state.stepCount = 0;
  updateStepCount();
  stopTimer();
  seenTabs.clear();
  if (tabBar) tabBar.hidden = true;
  // ponytail: clean up any lingering login-pause fallback buttons from a
  // previous task — a leftover Continue button is confusing once the user
  // is starting fresh.
  if (typeof document !== "undefined") {
    document.querySelectorAll(".login-continue-btn").forEach((el) => el.remove());
  }
  // ponytail: reset to initial empty-state by re-creating the placeholder so
  // the panel doesn't look empty.
  if (!document.getElementById("emptyState")) {
    messagesEl.appendChild(createEmptyState());
  }
}

function appendEmptyState() {
  messagesEl.appendChild(createEmptyState());
}

// ponytail: helper to fade out + remove the login_required bubble and
// its Continue button in one render frame. Called on resolve paths: the
// Continue button click, the next step_card after auto-resume, any
// agent input request (clarify / approval), and terminal events (done /
// error / fail). The fade matches the CSS .removing keyframe (180ms);
// DOM removal happens 20ms later so the fade isn't cut short.
function clearLoginPrompt() {
  const els = document.querySelectorAll('.login-required-msg, .login-continue-btn');
  if (els.length === 0) return;
  els.forEach((el) => el.classList.add('removing'));
  setTimeout(() => {
    els.forEach((el) => { if (el.isConnected) el.remove(); });
  }, 200);
}

function createEmptyState() {
  const div = document.createElement('div');
  div.className = 'empty-state';
  div.innerHTML = `
    <div class="empty-mark"><img src="assets/logo.svg" alt="Inventic" class="brand-logo brand-logo--lg"></div>
    <div class="empty-title">Brotto</div>
    <div class="empty-sub">Describe what you'd like to do in your browser and Brotto will get it done for you.</div>
  `;
  return div;
}

// ponytail: extract structured facts from the model's finalAnswer so
// the side panel can show URLs / order IDs / tracking IDs as a tidy
// list rather than buried in a wall of prose. Best-effort regex — no
// false positives in real-world text.
function renderFacts(finalAnswer) {
  if (!finalAnswer) return '';
  const urlRe = /\bhttps?:\/\/[^\s)\]'"<>]+/g;
  const orderIdRe = /\b(?:order\s*(?:#|number|id)|tracking\s*(?:id|number))\s*[:=]?\s*([A-Z0-9][-A-Z0-9]{4,})/gi;
  const dateRe = /\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\w*|\d{4}-\d{2}-\d{2})\b/gi;
  const urls = Array.from(new Set(finalAnswer.match(urlRe) || [])).slice(0, 5);
  const orderIds = Array.from(new Set(
    (finalAnswer.match(orderIdRe) || []).map((m) => m.replace(/^(?:order|tracking)\s*(?:#|number|id)?\s*:?\s*/i, '').trim())
  )).slice(0, 5);
  const dates = Array.from(new Set(finalAnswer.match(dateRe) || [])).slice(0, 5);
  if (urls.length === 0 && orderIds.length === 0 && dates.length === 0) return '';
  const lines = [];
  if (urls.length > 0) {
    lines.push('<div class="facts-group"><span class="facts-label">Links</span>');
    for (const u of urls) lines.push(`<a class="facts-link" href="${escapeHtml(u)}" target="_blank" rel="noreferrer">${escapeHtml(u)}</a>`);
    lines.push('</div>');
  }
  if (orderIds.length > 0) {
    lines.push('<div class="facts-group"><span class="facts-label">Identifiers</span>' +
      orderIds.map((id) => `<code class="facts-code">${escapeHtml(id)}</code>`).join(' ') + '</div>');
  }
  if (dates.length > 0) {
    lines.push('<div class="facts-group"><span class="facts-label">Dates</span>' +
      dates.map((d) => `<span class="facts-date">${escapeHtml(d)}</span>`).join(' ') + '</div>');
  }
  return `<div class="facts">${lines.join('')}</div>`;
}

function appendMessage({ role, text, inlineLogs, finalAnswer }) {
  // Remove empty state on first real message
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  const msg = document.createElement('div');
  msg.className = 'message ' + role;

  if (role === 'assistant' || role === 'user') {
    // Bubble wrapper
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = renderMarkdown(text);
    msg.appendChild(bubble);

    // Inline logs appended inside assistant bubble
    if (inlineLogs && inlineLogs.length > 0) {
      const logsDiv = document.createElement('div');
      logsDiv.className = 'inline-log';
      logsDiv.textContent = inlineLogs.join(' · ');
      bubble.appendChild(logsDiv);
    }
  } else if (role === 'system') {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    msg.appendChild(bubble);
  } else if (role === 'error') {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    msg.appendChild(bubble);
  } else if (role === 'done') {
    const bubble = document.createElement('div');
    bubble.className = 'bubble final-answer-bubble';

    if (finalAnswer) {
      const fa = document.createElement('div');
      fa.className = 'final-answer';
      const faText = document.createElement('div');
      faText.className = 'final-answer-text';
      faText.innerHTML = renderMarkdown(finalAnswer);
      fa.appendChild(faText);
      bubble.appendChild(fa);
    }

    // ponytail: bottom toolbar with feedback icons. Four icons — Copy,
    // Good (thumbs up), Bad (thumbs down), Retry — give the user a
    // single place to copy the answer, rate it, or re-run the same
    // task under a new session. The "Task completed · N steps" caption
    // is gone — the icon row replaces it.
    const toolbar = document.createElement('div');
    toolbar.className = 'final-answer-toolbar';

    if (finalAnswer) {
      // ponytail: copy includes the task + the final answer in a clean
      // markdown-style block. The user said "Show prompts as well when
      // copied the response" — the task is the prompt they sent, so
      // including it makes the copy self-contained when shared.
      const copyText = state.lastGoal
        ? `**Task:** ${state.lastGoal}\n\n**Response:**\n${finalAnswer}`
        : finalAnswer;
      const copyBtn = makeIconBtn(LUCIDE_ICONS.copy, 'Copy', async (ev) => {
        ev.stopPropagation();
        try {
          await navigator.clipboard.writeText(copyText);
        } catch {
          const ta = document.createElement('textarea');
          ta.value = copyText;
          ta.style.cssText = 'position:fixed;opacity:0';
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand('copy'); } catch {}
          document.body.removeChild(ta);
        }
        copyBtn.classList.add('clicked');
        setTimeout(() => copyBtn.classList.remove('clicked'), 1200);
      });
      toolbar.appendChild(copyBtn);
    }

    // ponytail: good/bad ratings are persistent and mutually exclusive.
    // Click toggles its own state — clicking the other deactivates the
    // first. The .rated-good / .rated-bad classes stay until the user
    // clicks again to clear.
    const goodBtn = makeIconBtn(LUCIDE_ICONS.thumbsUp, 'Good response', () => {
      if (goodBtn.classList.contains('rated-good')) {
        goodBtn.classList.remove('rated-good');
        return;
      }
      badBtn.classList.remove('rated-bad');
      goodBtn.classList.add('rated-good');
      recordFeedback('good');
    });
    toolbar.appendChild(goodBtn);

    const badBtn = makeIconBtn(LUCIDE_ICONS.thumbsDown, 'Bad response', () => {
      if (badBtn.classList.contains('rated-bad')) {
        badBtn.classList.remove('rated-bad');
        return;
      }
      goodBtn.classList.remove('rated-good');
      badBtn.classList.add('rated-bad');
      recordFeedback('bad');
    });
    toolbar.appendChild(badBtn);

    const retryBtn = makeIconBtn(LUCIDE_ICONS.retry, 'Retry', () => {
      retryLastTask();
    });
    toolbar.appendChild(retryBtn);

    bubble.appendChild(toolbar);
    msg.appendChild(bubble);
  }

  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return msg;
}

// ponytail: structured failure bubble for policy violations. Title +
// body + footer in a single red card so the user sees both the human-
// readable framing (set by renderPolicyFailureCard) and the actual
// harness summary that explains the specific incident. The footer is
// muted/grey so the eye lands on the body first.
function appendFailureBubble({ title, body, footer }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  const msg = document.createElement('div');
  msg.className = 'message error';

  const bubble = document.createElement('div');
  bubble.className = 'bubble failure-bubble';

  const titleEl = document.createElement('div');
  titleEl.className = 'failure-title';
  titleEl.textContent = title;
  bubble.appendChild(titleEl);

  if (body) {
    const bodyEl = document.createElement('div');
    bodyEl.className = 'failure-body';
    bodyEl.innerHTML = renderMarkdown(body);
    bubble.appendChild(bodyEl);
  }

  if (footer) {
    const footerEl = document.createElement('div');
    footerEl.className = 'failure-footer';
    footerEl.textContent = footer;
    bubble.appendChild(footerEl);
  }

  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return msg;
}

// ── Plan preview card ─────────────────────────────────────────────────────
function appendPlanCard({ title, sites, steps }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  const card = document.createElement('div');
  card.className = 'plan-card';

  const header = document.createElement('div');
  header.className = 'plan-header';
  header.innerHTML = `<span class="plan-badge">${title || "Brotto's plan"}</span>`;
  card.appendChild(header);

  if (sites && sites.length > 0) {
    const sitesDiv = document.createElement('div');
    sitesDiv.className = 'plan-sites';
    sitesDiv.innerHTML = `Allow actions on: <strong>${sites.join(', ')}</strong>`;
    card.appendChild(sitesDiv);
  }

  if (steps && steps.length > 0) {
    const approachTitle = document.createElement('div');
    approachTitle.className = 'plan-approach-title';
    approachTitle.textContent = 'Approach to follow:';
    card.appendChild(approachTitle);

    const ol = document.createElement('ol');
    ol.className = 'plan-steps';
    for (const step of steps) {
      const li = document.createElement('li');
      li.innerHTML = `<span class="plan-step-num">${step.index}.</span><span>${step.text}</span>`;
      ol.appendChild(li);
    }
    card.appendChild(ol);
  }

  const actions = document.createElement('div');
  actions.className = 'plan-actions';

  const approveBtn = document.createElement('button');
  approveBtn.className = 'btn btn-primary btn-sm';
  approveBtn.textContent = 'Approve plan';
  approveBtn.addEventListener('click', () => {
    appendMessage({ role: 'assistant', text: 'Approved the plan. Proceeding…' });
    card.remove();
  });
  actions.appendChild(approveBtn);

  const changeBtn = document.createElement('button');
  changeBtn.className = 'btn btn-sm';
  changeBtn.textContent = 'Make changes';
  changeBtn.addEventListener('click', () => {
    goalEl.focus();
  });
  actions.appendChild(changeBtn);

  card.appendChild(actions);
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ponytail: step bubble that tucks the raw tool call behind a "details"
// toggle so the chat reads naturally while still letting the operator
// drill in when debugging. Reasoning stays as the bubble title.
// ponytail: icon is set via innerHTML on its own <span> so HTML entities
// (&#8594;, &#9654;, &#10003;) decode to glyphs. The reasoning text uses
// textContent so any user/model-supplied HTML stays literal and safe.
function appendStepWithDetails({ icon, text, details, pageUrl, pageTitle, actionTarget }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  const msg = document.createElement('div');
  msg.className = 'message assistant';

  const bubble = document.createElement('div');
  bubble.className = 'bubble step-bubble';

  // ponytail: page/action chips. The page chip shows the URL the agent
  // was on (cleanUrl strips query/hash to avoid tokens in the chat).
  // The action chip shows the URL the agent was navigating to. When
  // navigated across the same domain to a different path, both chips
  // still differentiate via the path — keeping the host-only render
  // would have collapsed them to the same string.
  const pageClean = cleanUrl(pageUrl);
  const actionClean = cleanUrl(actionTarget);
  if (pageClean) {
    const chip = document.createElement('div');
    chip.className = 'step-page-chip';
    chip.innerHTML = `<span class="step-page-chip-icon">&#9655;</span><span class="step-page-chip-url">${escapeHtml(pageClean)}</span>`;
    bubble.appendChild(chip);
  }
  if (actionClean && actionClean !== pageClean) {
    const dest = document.createElement('div');
    dest.className = 'step-page-chip';
    dest.innerHTML = `<span class="step-page-chip-icon">&#8594;</span><span class="step-page-chip-url">${escapeHtml(actionClean)}</span>`;
    bubble.appendChild(dest);
  }

  const head = document.createElement('div');
  head.className = 'step-head';
  if (icon) {
    const iconEl = document.createElement('span');
    iconEl.className = 'step-head-icon';
    iconEl.innerHTML = icon;
    head.appendChild(iconEl);
    head.appendChild(document.createTextNode(' '));
  }
  const stepTextEl = document.createElement('span');
  stepTextEl.innerHTML = renderMarkdown(text || 'Working…');
  head.appendChild(stepTextEl);
  bubble.appendChild(head);

  if (details && details.length > 0) {
    const wrap = document.createElement('div');
    wrap.className = 'step-details';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'step-details-toggle';
    toggle.textContent = 'details';
    toggle.setAttribute('aria-expanded', 'false');

    const body = document.createElement('div');
    body.className = 'step-details-body';
    body.textContent = details;
    body.style.display = 'none';

    toggle.addEventListener('click', () => {
      const open = body.style.display !== 'none';
      body.style.display = open ? 'none' : 'block';
      toggle.setAttribute('aria-expanded', String(!open));
      toggle.textContent = open ? 'details' : 'hide details';
    });

    wrap.appendChild(toggle);
    wrap.appendChild(body);
    bubble.appendChild(wrap);
  }

  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return msg;
}

// ── Approval request card ─────────────────────────────────────────────────
// Actions the client should never paint as an approval card. The server
// is the source of truth, but this is defense-in-depth in case a future
// regression sends one of these.
const NON_APPROVABLE_ACTIONS = new Set([
  'task_complete', 'cannot_complete', 'ask_human',
  'write_scratchpad', 'append_scratchpad', 'read_scratchpad',
  'recall_memory',
]);

function appendApprovalCard({ id, reason, action }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  // Defense-in-depth: never render an approval card for a terminal,
  // internal, or question action. The server filters these too; if it
  // ever stops doing so, the user shouldn't see a button to "Approve
  // cannot_complete".
  if (NON_APPROVABLE_ACTIONS.has(action)) {
    console.warn('[brotto] suppressed approval card for non-approvable action:', action);
    // Still need to ACK so the server's queue doesn't hang. Send deny
    // so the harness aborts cleanly if it was awaiting this reply.
    if (id) void sendMessage({ type: 'submit_approval', id, approved: false });
    return;
  }

  const card = document.createElement('div');
  card.className = 'approval-card';

  const header = document.createElement('div');
  header.className = 'approval-header';
  header.innerHTML = `<span class="approval-badge">Approval needed</span>`;
  card.appendChild(header);

  if (reason) {
    const body = document.createElement('div');
    body.className = 'approval-body';
    body.textContent = reason;
    card.appendChild(body);
  }

  const preview = document.createElement('div');
  preview.className = 'approval-preview';
  const previewText = action?.url ? `${action.type ?? 'action'} → ${action.url}` : (action?.type ?? 'action');
  preview.textContent = previewText;
  preview.title = previewText;
  card.appendChild(preview);

  const actions = document.createElement('div');
  actions.className = 'approval-actions';

  const denyBtn = document.createElement('button');
  denyBtn.className = 'btn btn-danger btn-sm';
  denyBtn.textContent = 'Deny';
  denyBtn.addEventListener('click', () => {
    appendMessage({ role: 'assistant', text: 'Action denied.' });
    card.remove();
    void sendMessage({ type: 'submit_approval', id, approved: false });
  });
  actions.appendChild(denyBtn);

  const approveBtn = document.createElement('button');
  approveBtn.className = 'btn btn-primary btn-sm';
  approveBtn.textContent = 'Approve';
  approveBtn.addEventListener('click', () => {
    appendMessage({ role: 'assistant', text: 'Action approved.' });
    card.remove();
    void sendMessage({ type: 'submit_approval', id, approved: true });
    // ponytail: 5s post-approval revoke window. Show a small inline
    // affordance below the action bubble. If the user changes their
    // mind, the extension sends `revoke` to the server, which clears
    // approved_domains / seen_first_time so the next step re-prompts.
    const revoke = document.createElement('button');
    revoke.className = 'btn btn-secondary btn-sm revoke-btn';
    revoke.textContent = 'Revoke (5s)';
    let remaining = 5;
    const tick = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(tick);
        revoke.remove();
      } else {
        revoke.textContent = `Revoke (${remaining}s)`;
      }
    }, 1000);
    revoke.addEventListener('click', () => {
      clearInterval(tick);
      revoke.remove();
      void sendMessage({ type: 'send_to_server', payload: { type: 'revoke' } });
      appendMessage({ role: 'assistant', text: 'Approval revoked — next step will re-prompt.' });
    });
    // Insert after the last assistant message bubble.
    const lastBubble = messagesEl.querySelector('.message.assistant:last-child') || messagesEl;
    lastBubble.appendChild(revoke);
  });
  actions.appendChild(approveBtn);

  card.appendChild(actions);
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Clarify request card ─────────────────────────────────────────────────
function appendClarifyCard({ id, question, reason }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  // Remove any prior pending clarify card so we don't end up with stacked inputs.
  const prior = messagesEl.querySelector('.clarify-card');
  if (prior) prior.remove();

  const card = document.createElement('div');
  card.className = 'clarify-card';
  card.dataset.clarifyId = id;

  const header = document.createElement('div');
  header.className = 'clarify-header';
  header.innerHTML = `<span class="clarify-badge">Your input</span>`;
  card.appendChild(header);

  if (question) {
    const body = document.createElement('div');
    body.className = 'clarify-body';
    body.innerHTML = renderMarkdown(question);
    card.appendChild(body);
  }

  // Real text input INSIDE the card — previous version told the user to use
  // the bottom goalEl but that input was hard-coded to send a new task.
  const inputRow = document.createElement('div');
  inputRow.className = 'clarify-input-row';

  const input = document.createElement('textarea');
  input.className = 'clarify-input';
  input.rows = 1;
  input.placeholder = 'Type your answer…';
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 96) + 'px';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit(input.value, input, card);
    }
  });

  const sendBtn = document.createElement('button');
  sendBtn.className = 'clarify-send-btn';
  sendBtn.textContent = 'Send';
  sendBtn.addEventListener('click', () => void submit(input.value, input, card));

  inputRow.appendChild(input);
  inputRow.appendChild(sendBtn);
  card.appendChild(inputRow);

  const hint = document.createElement('div');
  hint.className = 'input-hint clarify-hint';
  hint.textContent = 'Press Enter to send · Shift+Enter for newline';
  card.appendChild(hint);

  const actions = document.createElement('div');
  actions.className = 'clarify-actions';

  const skipBtn = document.createElement('button');
  skipBtn.className = 'btn btn-sm';
  skipBtn.textContent = 'Skip';
  skipBtn.addEventListener('click', () => {
    appendMessage({ role: 'system', text: 'Skipped clarifying question.' });
    void sendMessage({ type: 'submit_clarification', id, answer: '' });
    card.remove();
    state.pendingClarifyId = null;
    setPhase(state.plannerUrl ? 'connected' : 'idle', state.plannerUrl ? 'Resuming…' : 'Idle');
  });
  actions.appendChild(skipBtn);

  card.appendChild(actions);
  messagesEl.appendChild(card);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  input.focus();

  state.pendingClarifyId = id;

  async function submit(value, inputEl, cardEl) {
    const answer = value.trim();
    if (!answer) {
      inputEl.focus();
      return;
    }
    appendMessage({ role: 'user', text: answer });
    cardEl.remove();
    state.pendingClarifyId = null;
    setPhase('connected', 'Resuming…');
    await sendMessage({ type: 'submit_clarification', id, answer });
  }
}

// ── Icon helpers (for step cards rendered as assistant messages) ───────────
function iconFor(kind) {
  switch (kind) {
    case 'left_click': case 'double_click': case 'right_click': case 'mouse_move': return '&#9654;';
    case 'insert_text': return '&#9998;';
    case 'visit_url': case 'history_back': return '&#8594;';
    case 'key': return '&#9251;';
    case 'terminate': return '&#10003;';
    case 'wait': case 'scroll': return '&#8226;';
    case 'error': return '&#10007;';
    case 'prompt': return '?';
    default: return '&#8594;';
  }
}

// ── Live assistant message (current "working" message being updated) ───────
let currentAssistantMsg = null;
let currentAssistantLogs = [];

function startAssistantMessage({ icon, title, meta }) {
  currentAssistantMsg = null;
  currentAssistantLogs = [];

  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

  const msg = document.createElement('div');
  msg.className = 'message assistant';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const iconEl = document.createElement('span');
  iconEl.style.marginRight = '5px';
  iconEl.style.opacity = '0.6';
  iconEl.innerHTML = icon || '&#8594;';

  const textNode = document.createTextNode(title || 'Working…');
  bubble.appendChild(iconEl);
  bubble.appendChild(textNode);

  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  currentAssistantMsg = { el: msg, bubble, textNode };
  return currentAssistantMsg;
}

function appendLogToAssistant(logText) {
  if (!currentAssistantMsg) return;
  const existing = currentAssistantMsg.bubble.querySelector('.inline-log');
  if (existing) {
    existing.textContent += ' · ' + logText;
  } else {
    const logsDiv = document.createElement('div');
    logsDiv.className = 'inline-log';
    logsDiv.textContent = logText;
    currentAssistantMsg.bubble.appendChild(logsDiv);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function finishAssistantMessage({ icon, title, meta }) {
  if (!currentAssistantMsg) {
    // Fallback: just append as a regular message
    appendMessage({ role: 'assistant', text: `${icon} ${title}${meta ? ' · ' + meta : ''}` });
    return;
  }
  // Finalize the bubble
  currentAssistantMsg.bubble.innerHTML = '';
  const iconEl = document.createElement('span');
  iconEl.style.marginRight = '6px';
  iconEl.style.opacity = '0.5';
  iconEl.innerHTML = icon || '&#8594;';
  const titleText = document.createTextNode(title || '');
  currentAssistantMsg.bubble.appendChild(iconEl);
  currentAssistantMsg.bubble.appendChild(titleText);

  if (meta) {
    const metaEl = document.createElement('div');
    metaEl.className = 'inline-log';
    metaEl.textContent = meta;
    currentAssistantMsg.bubble.appendChild(metaEl);
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
  currentAssistantMsg = null;
  currentAssistantLogs = [];
}

// ── Message listener (all event types from background.ts) ──────────────────

// ponytail: enterprise-grade failure rendering for policy violations.
// The cyber-team tone: no first-person, no apology, references the audit
// trail, gives a contact path, never blames the user. Returns null for
// non-policy failures so the existing generic render path is unchanged.
function renderPolicyFailureCard(message) {
  const reason = message.failure_reason;
  const summaryText = message.summary || '';
  if (reason === 'policy_blocked') {
    const blockedDomain = summaryText.match(/Blocked by policy:\s*(\S+)/)?.[1] || '(unknown)';
    return {
      title: "Action blocked by your organisation's security policy",
      body:
        "This task attempted to interact with a domain on your organisation's restricted list. "
        + "The action was stopped to protect company data. "
        + "If you need access for legitimate work, contact your IT administrator.",
      footer: 'Blocked domain: ' + blockedDomain,
    };
  }
  if (reason === 'user_denied') {
    return {
      title: 'Task stopped — approval not granted',
      body:
        'You declined an approval prompt during this task. The agent has stopped rather than continuing '
        + 'with an action you did not authorise. Start a new task to retry, or contact your administrator '
        + 'if you need help.',
    };
  }
  if (reason === 'policy_preflight') {
    // ponypnail: Agent declined upfront after seeing the org blacklist in
    // its preamble. The harness's `summary` is the agent's own reason
    // ("The organisation's security policy explicitly blacklists
    // mail.google.com. Navigating there would violate your organisation's
    // policy."). Show that as the body — it's the actual explanation, not
    // a paraphrase. Earlier code suppressed it on the grounds that the
    // preceding assistant bubble already stated it; in practice the
    // assistant card is a single line ("Checking the security policy
    // before navigating to Gmail.") and users miss the link.
    //
    // Extract the specific blocked domain if it's named in the summary,
    // so the footer surfaces it without the user having to read the body.
    const blockedDomain = summaryText.match(/blacklists?\s+([^\s.,;]+)/i)?.[1] || '';
    return {
      title: "Task not permitted by your organisation's security policy",
      body: summaryText ||
        "Brotto's policy preamble listed this task as out of scope for secure mode. "
        + "The agent declined the request before navigating anywhere. "
        + "Contact your IT administrator if you believe this is in error.",
      footer: blockedDomain ? `Blocked domain: ${blockedDomain}` : '',
    };
  }
  if (reason === 'CONNECTION_LOST') {
    // ponytail: WS died mid-task. The background emitted this event so
    // the user sees a structured explanation (not just "Task failed
    // (CONNECTION_LOST)") and understands the task state — the agent
    // can't continue, but their browser is fine and they can retry once
    // the server is back.
    return {
      title: 'Connection to server lost',
      body: "The agent lost contact with the Brotto server mid-task and can't continue from here. "
        + "Your browser is unaffected — start a new task once the server is back.",
    };
  }
  return null;
}

chrome.runtime.onMessage.addListener((message) => {
  switch (message.type) {

    case 'session_started':
      state.sessionId = message.sessionId || state.sessionId;
      break;

    // ponytail: Bug 3 — WS closed. The background emits a separate
    // `task_failed` event with reason CONNECTION_LOST when a task was
    // in-flight, so the timer stops and the failure bubble renders via
    // the existing task_failed handler. Here we just update the
    // connection pill; nothing else needs to happen on this event.
    case 'disconnected':
      setConnPill('reconnecting', 'Reconnecting…');
      break;

    // ponytail: Bug 4 — backoff state machine surfaces each attempt to
    // the user via the amber pill so the sidepanel feels alive.
    case 'reconnect_attempt':
      setConnPill('reconnecting', `Reconnecting… (attempt ${message.attempt ?? '?'})`);
      break;

    // ponytail: Bug 4 — backoff exhausted or user clicked Disconnect.
    // If a task was in flight, the CONNECTION_LOST bubble already
    // explained the situation; the pill flipping to 'Disconnected'
    // is enough. The earlier error message here duplicated that
    // explanation and added noise to the chat.
    case 'reconnect_giveup':
      setConnPill('error', 'Disconnected');
      break;

    case 'canonical_status': {
      // ponytail: normalize canonical lifecycle (completed / failed / cancelled /
      // disconnected / cancelling / waiting_for_approval) into the side-panel
      // phase enum so the UI doesn't get stuck in unmapped states. Do NOT
      // regress from a terminal phase ('error' / 'done') — the cancel
      // handler emits its own task_failed/canonical_status pair and a
      // late-arriving canonical_status from the loop's .then() must not
      // overwrite the already-correct terminal pill.
      const raw = String(message.status || '');
      if (state.phase === 'error' || state.phase === 'done') {
        logSilently(`canonical_status ${raw} arrived after terminal phase ${state.phase}; ignored`);
        break;
      }
      const mapped = (raw === 'completed' || raw === 'cancelled' || raw === 'disconnected') ? 'done'
        : raw === 'failed' ? 'error'
        : raw === 'cancelling' ? 'paused'
        : raw === 'waiting_for_approval' ? 'paused'
        : raw;
      const meta = message.reconnectAttempt !== undefined
        ? `Reconnecting (${message.reconnectAttempt})…`
        : raw === 'completed' ? 'Task complete'
        : raw === 'failed' ? 'Task failed'
        : raw === 'cancelled' ? 'Task cancelled'
        : null;
      setPhase(mapped, meta);
      break;
    }

    case 'step_card': {
      // ponytail: any new step implies login was resolved (the loop only
      // emits step_progress after the human_input_queue unblocks). Fade
      // the bubble + button out before rendering the new step so the
      // user sees a continuous flow, not two bubbles stacked.
      clearLoginPrompt();
      state.stepCount = Math.max(state.stepCount, message.index !== undefined ? message.index + 1 : state.stepCount + 1);
      updateStepCount();
      const icon = iconFor(message.iconKind || '');
      // ponytail: prefer the model's `clientText` (one-line user-facing update)
      // as the bubble title. Fall back to reasoning only when clientText is
      // missing — older models emit a single `reasoning` field. Last-resort
      // fallback: derive from the raw action type so the bubble is never
      // empty. This split keeps internal jargon (phase names, criterion ids,
      // scratchpad bullets) out of the chat the user reads.
      const bubbleTitle = (message.clientText && message.clientText.trim())
        || (message.reasoning && message.reasoning.trim())
        || deriveReasoningFromAction(message.title || '', message.iconKind);
      // ponytail: the details panel shows tool call names ONLY when the
      // step had multiple actions. Single-action steps keep the bubble
      // content as the only detail (the raw tool call args are hidden —
      // the user said they don't want to see complete tool calls).
      // Multi-action steps list the names joined by ", " so the operator
      // can see at a glance which tools fired in this batch.
      const actions = Array.isArray(message.actions) ? message.actions : [];
      const details = actions.length > 1
        ? actions.map(a => a.action).filter(Boolean).join(', ')
        : '';
      // ponytail: each step gets its OWN persistent bubble. clientText is the
      // bubble title; raw tool call + reasoning live behind a "details"
      // toggle so the chat reads naturally and the operator can drill in
      // when debugging. Icon is passed separately so HTML entities decode
      // instead of rendering as literal `&#8594;`.
      appendStepWithDetails({ icon, text: bubbleTitle, details, ts: message.ts, pageUrl: message.url, pageTitle: message.pageTitle, actionTarget: message.actionTarget ?? null });
      // Track context utilization for the CONTEXT cell. Backend ships
      // `{tokens, window, pct}` per step (pct is the model-reported
      // usage / model's context window). Frontend just stores and
      // renders — no math here.
      if (message.context && typeof message.context === 'object') {
        state.lastContext = message.context;
      }
      updateContextUsage();
      break;
    }

    case 'log':
      // ponytail: historical handler kept for back-compat. New background
      // logs go to the service worker console only; UI stays clean.
      break;

    case 'login_required':
      setPhase('paused', `Login required at ${message.domain || 'site'}`);
      // ponytail: dedupe via clearLoginPrompt so the old bubble + button
      // fade out instead of being yanked from the layout (which causes a
      // visible jump when the next bubble appears).
      clearLoginPrompt();
      const domain = message.domain || 'this site';
      const loginMsg = document.createElement('div');
      loginMsg.className = 'message assistant login-required-msg';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      const badge = document.createElement('div');
      badge.className = 'login-required-badge';
      badge.textContent = `Waiting for sign-in · ${domain}`;
      const body = document.createElement('div');
      body.className = 'login-required-body';
      body.textContent = 'Sign in manually in the browser tab. The task resumes automatically once the post-login page loads. Use Continue only if auto-resume does not fire.';
      bubble.appendChild(badge);
      bubble.appendChild(body);
      loginMsg.appendChild(bubble);
      messagesEl.appendChild(loginMsg);
      // ponytail: safety-net Continue button. Primary resume path is
      // webNavigation.onCommitted firing off the login domain, but that
      // misses some SPAs and OAuth callback flows. The button is a manual
      // override — clicking it fades both bubble + button out and signals
      // resume to the loop. Cleaned up automatically on next step / task
      // end so it never lingers into the next task.
      const continueBtn = document.createElement('button');
      continueBtn.type = 'button';
      continueBtn.className = 'login-continue-btn';
      continueBtn.textContent = 'Continue';
      continueBtn.addEventListener('click', () => {
        continueBtn.disabled = true;
        // ponytail: clearLoginPrompt runs in the same render frame as the
        // click, so the bubble + button fade out together. The local_login_complete
        // signal goes out in parallel — the loop unblocks as soon as the
        // SW relays the human_reply, and the next step_card will arrive
        // immediately after with no gap.
        clearLoginPrompt();
        try {
          chrome.runtime.sendMessage({ type: 'local_login_complete' }, () => {
            void chrome.runtime.lastError;
          });
        } catch { /* SW gone — user can re-trigger */ }
      });
      messagesEl.appendChild(continueBtn);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      break;

    case 'context_update': {
      // ponytail: scratchpad-only step (no external action visible to
      // bubble). Backend still emits context so the CONTEXT cell updates
      // on every step.
      if (message.context && typeof message.context === 'object') {
        state.lastContext = message.context;
      }
      updateContextUsage();
      break;
    }

    case 'task_completed':
      // ponytail: clear any lingering login prompt — task is ending, no
      // point leaving the user looking at a "Waiting for sign-in" bubble.
      clearLoginPrompt();
      stopTimer();
      setPhase('done', message.summary ? message.summary.slice(0, 60) : 'Task complete');
      state.stepCount = message.steps || state.stepCount;
      updateStepCount();
      let messageText = `${message.steps || state.stepCount} steps · ${message.summary || ''}`;
      // If extracted_data exists, append it as structured facts (already formatted by agent)
      if (message.extracted_data && typeof message.extracted_data === 'object') {
        const facts = Object.entries(message.extracted_data)
          .filter(([, v]) => v && typeof v === 'string')
          .map(([k, v]) => {
            const label = k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            return `${label}: ${v}`;
          })
          .join(' | ');
        if (facts) messageText += `\n\n${facts}`;
      }
      if (message.timing && message.timing.components) {
        const c = message.timing.components;
        const ms = (s) => `${(s * 1000).toFixed(0)}ms`;
        messageText += `\n\nTiming (${message.timing.steps} steps, ${message.timing.wall_s.toFixed(1)}s wall): ` +
          `observe=${ms(c.observe)}  plan=${ms(c.model_plan)}  exec=${ms(c.execute)}  ` +
          `login=${ms(c.login_pause)}  other=${ms((c.filter ?? 0) + (c.stagnation ?? 0) + (c.approval_pause ?? 0) + (c.ws_send_progress ?? 0))}`;
      }
      appendMessage({
        role: 'done',
        text: messageText,
        finalAnswer: message.finalAnswer,
      });
      break;

    case 'task_failed':
      // ponytail: same as task_completed — clean up login prompt on any
      // terminal event so the user never sees a stale "Waiting" bubble
      // after the task has failed / been cancelled.
      clearLoginPrompt();
      stopTimer();
      // ponytail: structured failure bubble (title + body + footer) for
      // policy failures; falls back to the harness's `summary` for everything
      // else so the user always sees WHY the task failed, not just the
      // code. The earlier version suppressed the bubble entirely for
      // `policy_preflight` on the theory that the preceding assistant
      // card already explained it — in practice that card is one line
      // ("Checking the security policy before navigating to Gmail.") and
      // the link to the actual reason was easy to miss.
      const policyMsg = renderPolicyFailureCard(message);
      if (policyMsg) {
        setPhase('error', policyMsg.title);
        // ponytail: title is set via setPhase above; render a structured
        // bubble with the body and a separate footer so the blocked
        // domain + reference ID don't get lost in the prose.
        appendFailureBubble({
          title: policyMsg.title,
          body: policyMsg.body,
          footer: policyMsg.footer,
        });
      } else {
        // Non-policy failure: surface the harness's `summary` verbatim so
        // the user sees the actual reason (e.g. network error, model
        // refusal, missing login). Falls back to the failure_reason code
        // only when the harness didn't include a summary.
        const failMsg = message.summary || message.failure_reason || 'Task failed';
        setPhase('error', message.failure_reason ? `Task failed (${message.failure_reason})` : 'Task failed');
        appendMessage({ role: 'error', text: failMsg });
      }
      break;

    case 'clarify_request': {
      // ponytail: login wall was cleared (otherwise the loop couldn't
      // have produced a clarifying question). Fade bubble + button out
      // before the new clarify card appears so the transition reads as
      // a single flow, not two stacked bubbles.
      clearLoginPrompt();
      setPhase('paused', 'Clarifying question from agent');
      appendClarifyCard({
        id: message.id,
        question: message.question || 'The agent needs your guidance.',
        reason: message.reason || '',
      });
      break;
    }

    case 'approval_request': {
      // ponytail: same as clarify — login resolved before an approval
      // request could fire. Fade login prompt out so the approval card
      // is the only new element on screen.
      clearLoginPrompt();
      setPhase('paused', 'Agent wants approval for a critical action');
      const a = message.action || {};
      const preview = a.url ? `${a.type ?? 'action'} → ${a.url}` : (a.type ?? 'action');
      appendApprovalCard({
        id: message.id,
        reason: message.reason || 'The agent wants to perform an action that needs your approval.',
        action: { type: a.type, url: a.url },
      });
      break;
    }

    // ── Canonical events ─────────────────────────────────────────────────
    case 'canonical_step': {
      // ponytail: any canonical step past a login wall clears the prompt.
      clearLoginPrompt();
      const icon = message.kind === 'action' ? '&#9654;' : message.kind === 'observation' ? '&#128065;' : '&#10003;';
      const titleText = (message.reasoning && message.reasoning.trim())
        || deriveReasoningFromAction(message.summary || '', message.kind)
        || 'Working on it…';
      if (!currentAssistantMsg) {
        startAssistantMessage({ icon, title: titleText });
      }
      break;
    }

    case 'canonical_approval': {
      const req = message.request || {};
      // ponytail: same as approval_request — login must be resolved.
      clearLoginPrompt();
      setPhase('paused', 'Agent is requesting approval');
      appendApprovalCard({
        id: req.actionId || 'unknown',
        reason: 'The agent is requesting approval for a sensitive action.',
        action: { type: req.action?.type },
      });
      break;
    }

    case 'canonical_terminal': {
      // ponytail: terminal event from the canonical stream — clean up
      // any login prompt so it doesn't survive past the task ending.
      clearLoginPrompt();
      stopTimer();
      const m = message.message || {};
      if (m.type === 'task.completed') {
        setPhase('done', m.summary || 'Task complete');
        appendMessage({ role: 'done', text: m.summary || 'Task completed successfully.', finalAnswer: m.finalAnswer });
      } else if (m.type === 'task.failed') {
        setPhase('error', m.message || 'Task failed');
        appendMessage({ role: 'error', text: m.message || 'Task failed.' });
      } else {
        setPhase('done', 'Task ended');
        appendMessage({ role: 'done', text: 'Task ended.' });
      }
      break;
    }

    case 'canonical_error':
      appendMessage({ role: 'error', text: `${message.code}: ${message.message}` });
      break;

    case 'canonical_reconnect':
      setPhase('reconnecting', `Reconnecting (attempt ${message.attempt})…`);
      break;

    // ── Plan preview (from orchestrator) ─────────────────────────────────
    // Side panel receives a plan event when the orchestrator emits a plan.
    // Background does not currently emit this; the handler is ready.
    case 'plan': {
      appendPlanCard({
        title: message.title || "Brotto's plan",
        sites: message.sites || [],
        steps: message.steps || [],
      });
      break;
    }

    case 'tab_event': {
      // ponytail: local-driver tab lifecycle — render to the tabs row.
      recordTabEvent(message.event);
      break;
    }
  }
});

// ── Initial state ────────────────────────────────────────────────────────
setPhase('idle', 'Ready');
goalEl.focus();

// Auto-probe health on open — marks the planner as reachable if the server responds.
(async () => {
  const url = plannerUrlEl.value.trim() || 'http://localhost:8000';
  try {
    const res = await fetch(url + '/health', { method: 'GET' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.plannerUrl = url;
  } catch {
    // ponytail: Bug 9 — server unreachable on open. Surface a one-line
    // toast so the user knows their UI isn't actually wired to a live
    // server. Auto-dismiss after 5s. Don't mark plannerUrl so the
    // connection pill stays in the default "Idle" state.
    state.serverReachable = false;
    setConnPill(null, 'Server unreachable');
    appendMessage({ role: 'error',
      text: '⚠ Server unreachable — settings still work locally. Will auto-reconnect when it returns.',
    });
    // Don't keep the toast around forever; remove the most-recent error
    // message after 5s so the chat stays clean for the next prompt.
    setTimeout(() => {
      const messages = messagesEl.querySelectorAll('.message-error');
      if (messages.length) {
        const oldest = messages[0];
        if (oldest.textContent && oldest.textContent.includes('Server unreachable')) {
          oldest.remove();
        }
      }
    }, 5000);
  }
})();
