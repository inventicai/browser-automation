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
// ponytail: tab-bar handles — render each lifecycle event (open/close/nav/
// focus) as a row so the user sees what the agent touched in their browser.
const tabBar         = document.getElementById('tabBar');
const tabBarBody     = document.getElementById('tabBarBody');
const tabBarToggle   = document.getElementById('tabBarToggle');

// ── Settings panel ────────────────────────────────────────────────────────
settingsBtn.addEventListener('click', () => {
  plannerUrlSetting.value = plannerUrlEl.value || 'http://localhost:8000';
  settingsOverlay.classList.add('open');
});

// ponytail: tab-bar — collapsed/expanded by default. Each row shows badge
// (kind), title (or url), and a one-line context line.
const seenTabs = new Map(); // tabId → {kind, url, title, lastUpdate}
let tabBarCollapsed = false;
function renderTabBar() {
  if (!tabBarBody) return;
  tabBarBody.replaceChildren();
  if (seenTabs.size === 0) {
    const empty = document.createElement('div');
    empty.className = 'tab-row-empty';
    empty.textContent = 'No tabs opened by the agent.';
    tabBarBody.appendChild(empty);
    tabBar.hidden = false;
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
    const idEl = document.createElement('span');
    idEl.className = 'tab-row-url';
    idEl.textContent = `#${row.tabId}`;
    row_el.appendChild(idEl);
    tabBarBody.appendChild(row_el);
  }
  tabBar.hidden = false;
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

// Minimal markdown renderer for agent output — bold, italic, inline code, links, line breaks.
// HTML-escapes first so injected HTML stays literal; only our own tags get through.
function renderMarkdown(raw) {
  if (!raw) return '';
  let s = escapeHtml(String(raw));
  s = s.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  s = s.replace(/\*(.+?)\*/g, '<i>$1</i>');
  s = s.replace(/`([^`\n]+)`/g, '<code style="background:var(--surface-2);padding:1px 4px;border-radius:3px;font-size:0.88em;font-family:ui-monospace,monospace">$1</code>');
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  s = s.replace(/\n/g, '<br>');
  return s;
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
  appendMessage({ role: 'system', text: `Connected to planner at ${url}` });
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
      '<div class="empty-mark"><svg class="brand-mark brand-mark--lg" viewBox="0 0 32 32" aria-hidden="true"><path d="M5 24 L14 8 L18 14 L23 19 L26 22 Z" fill="#0052CC"/><path d="M18 14 L23 19 L26 22 L24 22 L19 18 Z" fill="#6DB3D8"/></svg></div>' +
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
    appendMessage({ role: 'system', text: `Connected to planner at ${url}` });
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
    <div class="empty-mark"><svg class="brand-mark brand-mark--lg" viewBox="0 0 32 32" aria-hidden="true"><path d="M5 24 L14 8 L18 14 L23 19 L26 22 Z" fill="#0052CC"/><path d="M18 14 L23 19 L26 22 L24 22 L19 18 Z" fill="#6DB3D8"/></svg></div>
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
    bubble.innerHTML = `<strong>Error:</strong> ${text}`;
    msg.appendChild(bubble);
  } else if (role === 'done') {
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    // ponytail: clean done-message layout. finalAnswer is the model's
    // plain-English answer — show it as the primary content. Below it,
    // extract structured facts (URLs, order IDs, tracking IDs, dates)
    // as a clean list. Avoid duplicating the answer in a summary line.
    const stepsMatch = (text || '').match(/^(\d+)\s*steps?\b/i);
    const stepCount = stepsMatch ? stepsMatch[1] : '';
    const finalAnswerHtml = finalAnswer
      ? `<div class="final-answer"><div class="final-answer-text">${renderMarkdown(finalAnswer)}</div></div>`
      : '';
    const factsHtml = finalAnswer ? renderFacts(finalAnswer) : '';
    const captionHtml =
      `<div class="done-caption">` +
      `<span class="done-icon">&#10003;</span> Task completed` +
      (stepCount ? ` &middot; ${stepCount} steps` : '') +
      `</div>`;
    bubble.innerHTML = finalAnswerHtml + factsHtml + captionHtml;
    msg.appendChild(bubble);
  }

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

  // ponytail: page context chip — shows what the agent was looking at
  // when it decided this action. Without this, the agent's reasoning
  // ("the browser is on a blank page") reads as out-of-date by the time
  // the user sees the bubble, because the page has already changed.
  // Anchoring each step to its captured page state removes the temporal
  // disconnect between reasoning text and visible browser tab.
  const domainOf = (url) => { try { return new URL(url).hostname; } catch { return url; } };
  if (pageUrl) {
    const chip = document.createElement('div');
    chip.className = 'step-page-chip';
    chip.innerHTML = `<span class="step-page-chip-icon">&#9655;</span><span class="step-page-chip-url">${escapeHtml(domainOf(pageUrl))}</span>`;
    bubble.appendChild(chip);
  }
  if (actionTarget) {
    const dest = document.createElement('div');
    dest.className = 'step-page-chip';
    dest.innerHTML = `<span class="step-page-chip-icon">&#8594;</span><span class="step-page-chip-url">${escapeHtml(domainOf(actionTarget))}</span>`;
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
function appendApprovalCard({ id, reason, action }) {
  const empty = messagesEl.querySelector('.empty-state');
  if (empty) empty.remove();

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
    body.textContent = question;
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
chrome.runtime.onMessage.addListener((message) => {
  switch (message.type) {

    case 'session_started':
      state.sessionId = message.sessionId || state.sessionId;
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
      // ponytail: the details panel shows the raw tool call AND, when present,
      // the model's internal reasoning — so the operator can drill in for
      // debugging while the user-facing chat stays clean.
      const detailsLines = [`${message.title || ''}${message.result ? ' → ' + message.result : ''}`.trim()];
      if (message.reasoning && message.clientText && message.reasoning.trim() !== message.clientText.trim()) {
        detailsLines.push(`--- reasoning ---\n${message.reasoning.trim()}`);
      }
      const details = detailsLines.filter(Boolean).join('\n');
      // ponytail: each step gets its OWN persistent bubble. clientText is the
      // bubble title; raw tool call + reasoning live behind a "details"
      // toggle so the chat reads naturally and the operator can drill in
      // when debugging. Icon is passed separately so HTML entities decode
      // instead of rendering as literal `&#8594;`.
      appendStepWithDetails({ icon, text: bubbleTitle, details, ts: message.ts, pageUrl: message.url, pageTitle: message.pageTitle, actionTarget: message.actionTarget ?? null });
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
      setPhase('error', message.message || 'Task failed');
      appendMessage({
        role: 'error',
        text: `${message.code || 'Error'}: ${message.message || 'Task failed'}`,
      });
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
    // Server not reachable — leave state.plannerUrl unset so the UI shows idle.
  }
})();
