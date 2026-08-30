/**
 * Brotto background service worker.
 * Thin relay: captures AX tree from the active tab, sends observations to the
 * orchestrator over WebSocket, executes actions returned by the agent.
 */

import * as dbg from "./debugger";

const DEFAULT_SERVER = "http://localhost:8000";

const KEEP_ROLES = new Set([
  "button","link","textbox","searchbox","combobox","checkbox","radio",
  "menuitem","tab","option","switch","slider","spinbutton","gridcell",
  "heading","dialog","alert","listitem",
]);

const BADGE_ACTIVE = "#22c55e";
const BADGE_IDLE   = "#6b7280";

// ── State ───────────────────────────────────────────────────────────────────

let ws: WebSocket | null = null;
let activeTabId: number | null = null;
let tabStack: number[] = []; // opener history for back-navigation
let sessionId: string | null = null;
let serverUrl: string = DEFAULT_SERVER;
let taskTerminalEmitted = false;
let stepIndex = 0;
// ponytail: Bug B-fix — distinguish "task running, server died" from
// "task finished cleanly, no need to keep the WS alive". Without this
// flag, scheduleReconnect() opens a fresh WS after every clean task
// end. The new WS has no task_start to send (the initial startRelay
// path is the only sender), so the server's heartbeat ping arrives
// as the first message ~20s later and the server logs
// "expected task_start, got ping" before closing. Auto-reconnect is
// only meaningful when an in-flight task needs the WS back.
let taskInFlight = false;

// ponytail: Bug 4 — auto-reconnect state. Tracks attempts, target URL,
// and whether the user has explicitly disconnected (in which case we
// do NOT auto-reconnect, even if the WS dies).
let reconnectAttempts = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let userInitiatedDisconnect = false;
// ponytail: 3 attempts at 5s flat. Earlier we used exponential backoff
// (1s → 2s → 4s → 8s → 16s → 30s, 5 attempts max) — that surfaced
// "Reconnecting… (attempt 5)" to the user and made the failure feel
// unbounded. The user wants a short, predictable window: try 3 times
// at 5s intervals, then surface the failure and require a manual
// Connect. The reconnect is for the NEXT task; the in-flight task is
// already lost when the WS dies (handled in cleanup()).
const MAX_RECONNECT_ATTEMPTS = 3;
const BASE_RECONNECT_DELAY_MS = 5000;

// ponytail: Bug 5 — heartbeat. Without this, the only signal that the
// server is dead is the OS-level TCP timeout (can be minutes). With a
// 20s ping + 30s pong-deadline, the SW detects server loss within
// ~30s of the actual outage rather than waiting on the kernel.
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let lastPongAt = 0;
const HEARTBEAT_INTERVAL_MS = 20_000;
const HEARTBEAT_DEADLINE_MS = 30_000;

function startHeartbeat(): void {
  stopHeartbeat();
  lastPongAt = Date.now();
  heartbeatTimer = setInterval(() => {
    // If the WS is closed/closing, the server is unreachable from our
    // perspective and cleanup() is already running. Skip the ping.
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (Date.now() - lastPongAt > HEARTBEAT_DEADLINE_MS) {
      console.warn("[brotto] heartbeat deadline missed — forcing reconnect");
      try { ws.close(); } catch { /* ignore */ }
      return; // onclose → cleanup → scheduleReconnect
    }
    try {
      ws.send(JSON.stringify({ type: "ping" }));
    } catch {
      try { ws.close(); } catch { /* ignore */ }
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat(): void {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}
// ponytail: monotonic observation seq per session. The server's
// obs_validator dedupes on this so duplicate WS deliveries (reconnects,
// queued messages) are dropped silently. Reset on a new session — the
// server's tracker is also freshly created on `/v1/sessions`.
let observationSeq = 0;

// Pause state — persists across SW restarts via chrome.storage.session so a
// quiet login page doesn't lose the "we're waiting for the user" signal.
let waitingForLogin = false;
let currentPrompt: "login" | "approval" | "clarify" | null = null;
let lastObservedUrl = "";

// User-side policy: persisted in chrome.storage.local (settings key) and
// refreshed in-memory on `policy_changed` from the sidepanel. Sent as
// `user_policy` on each task_start; the server merges with the floor.
// ponytail: write-on-save only — no debounce, no reactivity layer.
// ponytail: whitelist was removed in the enterprise redesign — secure
// mode now means "hard-block blacklisted + first-time-seen prompts on
// new (domain, action) pairs". Keeping the type narrow to what we ship.
let userPolicy: { mode: "normal" | "secure"; blacklist: string[] } = {
  mode: "normal",
  blacklist: [],
};

// ponytail: Bug 1 — SW hydration on startup. Without this, every
// extension reload resets userPolicy to defaults even though the user
// saved a secure-mode policy. The sidepanel writes to chrome.storage
// .local on Save; we mirror it into the SW's in-memory `userPolicy`
// here so the next task_start ships the correct view.
async function hydrateUserPolicy(): Promise<void> {
  try {
    const stored = await chrome.storage.local.get("settings");
    const s = stored.settings as
      | { mode?: string; blacklist?: unknown }
      | undefined;
    if (!s) return;
    userPolicy = {
      mode: s.mode === "secure" ? "secure" : "normal",
      blacklist: Array.isArray(s.blacklist)
        ? s.blacklist.filter((d): d is string => typeof d === "string")
        : [],
    };
    console.log("[brotto] userPolicy hydrated from storage:", userPolicy);
  } catch (e) {
    console.warn("[brotto] hydrateUserPolicy failed (using defaults):", e);
  }
}

const pendingClarifyResolvers  = new Map<string, (answer: string) => void>();
const pendingApprovalResolvers = new Map<string, (approved: boolean) => void>();
let reqCounter = 0;
function newId(prefix: string) { return `${prefix}-${Date.now().toString(36)}-${++reqCounter}`; }

// ── Session persistence (survives SW suspension/restart) ────────────────────

async function persistSession(): Promise<void> {
  await chrome.storage.session.set({
    sessionId,
    activeTabId,
    serverUrl,
    waitingForLogin,
    currentPrompt,
    lastObservedUrl,
  });
}

async function restoreSession(): Promise<void> {
  const s = await chrome.storage.session.get([
    "sessionId", "activeTabId", "serverUrl", "waitingForLogin", "currentPrompt", "lastObservedUrl",
  ]);
  if (typeof s.sessionId === "string") sessionId = s.sessionId;
  if (typeof s.activeTabId === "number") activeTabId = s.activeTabId;
  if (typeof s.serverUrl === "string") serverUrl = s.serverUrl;
  if (typeof s.waitingForLogin === "boolean") waitingForLogin = s.waitingForLogin;
  if (s.currentPrompt === "login" || s.currentPrompt === "approval" || s.currentPrompt === "clarify") {
    currentPrompt = s.currentPrompt;
  }
  if (typeof s.lastObservedUrl === "string") lastObservedUrl = s.lastObservedUrl;
}

async function clearSession(): Promise<void> {
  await chrome.storage.session.clear();
  sessionId = null;
  activeTabId = null;
  waitingForLogin = false;
  currentPrompt = null;
  lastObservedUrl = "";
}

// Send the user's reply for whichever prompt is current and clear the wait.
function signalResume(): void {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "human_reply", content: "resume" }));
  waitingForLogin = false;
  currentPrompt = null;
  void persistSession();
}

// ── AX tree capture ─────────────────────────────────────────────────────────

async function extractAx(tabId: number): Promise<object[]> {
  await dbg.sendCommand(tabId, { method: "Accessibility.enable" });
  const raw = await dbg.sendCommand(tabId, {
    method: "Accessibility.getFullAXTree",
  }) as { nodes?: any[] };
  const nodes = raw.nodes ?? [];
  const targets: object[] = [];

  for (const node of nodes) {
    if (node.ignored) continue;
    const role = (node.role?.value ?? "").toLowerCase();
    if (!KEEP_ROLES.has(role)) continue;
    const name  = node.name?.value?.trim() ?? "";
    const value = node.value?.value ?? undefined;
    const backendId = node.backendDOMNodeId;
    let x: number | undefined, y: number | undefined;
    if (backendId) {
      try {
        const box = await dbg.sendCommand(tabId, {
          method: "DOM.getBoxModel",
          params: { backendNodeId: backendId },
        }) as { model?: { content?: number[] } };
        const c = box.model?.content;
        if (c && c.length >= 4) {
          x = Math.round((c[0] + c[2]) / 2);
          y = Math.round((c[1] + c[3]) / 2);
        }
      } catch { /* offscreen — skip coords */ }
    }
    targets.push({
      ref: node.nodeId, role, name,
      ...(value !== undefined ? { value } : {}),
      ...(x !== undefined    ? { x, y }   : {}),
    });
  }
  await dbg.sendCommand(tabId, { method: "Accessibility.disable" });
  return targets;
}

async function captureObservation(tabId: number) {
  await waitForPageReady(tabId);

  const ps = await dbg.sendCommand(tabId, {
    method: "Runtime.evaluate",
    params: { expression: "({url:location.href,title:document.title})", returnByValue: true },
  }) as { result?: { value?: { url: string; title: string } } };
  const { url = "", title = "" } = ps.result?.value ?? {};

  let axTargets = await extractAx(tabId);

  // SPA pages render interactives after readyState — retry with backoff
  for (let i = 0; i < 4 && axTargets.length < 3; i++) {
    await sleep(800 * (i + 1));
    axTargets = await extractAx(tabId);
  }

  return { url, title, axTargets };
}

// ── Action execution ─────────────────────────────────────────────────────────

async function executeAction(tabId: number, action: any): Promise<void> {
  const t = action.type;
  if (t === "navigate") {
    await dbg.sendCommand(tabId, { method: "Page.navigate", params: { url: action.url } });
    await sleep(200); // brief pause for navigation to start before readyState polling
  } else if (t === "click") {
    const { x, y } = action;
    await dbg.sendCommand(tabId, { method: "Input.dispatchMouseEvent", params: { type: "mousePressed", x, y, button: "left", clickCount: 1 } });
    await dbg.sendCommand(tabId, { method: "Input.dispatchMouseEvent", params: { type: "mouseReleased", x, y, button: "left", clickCount: 1 } });
    await sleep(200); // brief pause for click to register / navigation to start
  } else if (t === "type") {
    for (const ch of (action.text ?? "") as string) {
      await dbg.sendCommand(tabId, { method: "Input.dispatchKeyEvent", params: { type: "char", text: ch } });
    }
  } else if (t === "scroll") {
    await dbg.sendCommand(tabId, {
      method: "Input.dispatchMouseEvent",
      params: { type: "mouseWheel", x: 400, y: 300, deltaX: 0, deltaY: action.deltaY ?? 300 },
    });
    await sleep(300);
  } else if (t === "key") {
    await dbg.sendCommand(tabId, { method: "Input.dispatchKeyEvent", params: { type: "keyDown", key: action.key } });
    await dbg.sendCommand(tabId, { method: "Input.dispatchKeyEvent", params: { type: "keyUp",   key: action.key } });
  }
}

function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

async function waitForPageReady(tabId: number, maxWaitMs = 10_000): Promise<void> {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    try {
      const r = await dbg.sendCommand(tabId, {
        method: "Runtime.evaluate",
        params: { expression: "document.readyState", returnByValue: true },
      }) as { result?: { value?: string } };
      if (r.result?.value === "complete") {
        await sleep(400); // let JS frameworks render
        return;
      }
    } catch { /* tab mid-navigation — keep polling */ }
    await sleep(300);
  }
  // timed out — proceed with whatever is there
}

// ── Sidepanel notifications ──────────────────────────────────────────────────

function notifyUi(event: Record<string, unknown>): void {
  void chrome.runtime.sendMessage(event).catch(() => undefined);
}

async function setBadge(active: boolean): Promise<void> {
  await chrome.action.setBadgeBackgroundColor({ color: active ? BADGE_ACTIVE : BADGE_IDLE });
  await chrome.action.setBadgeText({ text: active ? "ON" : "" });
}

// ── WebSocket observation sender ─────────────────────────────────────────────

async function sendObservation(tabId: number): Promise<void> {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  try {
    const obs = await captureObservation(tabId);
    ws.send(JSON.stringify({ type: "observation", seq: ++observationSeq, ...obs }));
    if (typeof obs.url === "string" && obs.url !== lastObservedUrl) {
      lastObservedUrl = obs.url;
      void persistSession();
    }
    // Keep tab bar in sync with every navigation within the active tab
    notifyUi({ type: "tab_event", event: { kind: "navigated", tabId, url: obs.url, title: obs.title } });
  } catch (e) {
    ws.send(JSON.stringify({ type: "observation_error", error: String(e) }));
  }
}

// ── Main relay ───────────────────────────────────────────────────────────────

async function startRelay(goal: string, plannerUrl: string, startingUrl?: string): Promise<void> {
  serverUrl = plannerUrl;
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const activeTab = tabs[0];

  let tab: chrome.tabs.Tab;
  let needsNavigate = !!startingUrl;

  if (activeTab?.id && activeTab.url && /^https?:\/\//i.test(activeTab.url)) {
    tab = activeTab;
  } else {
    // Non-HTTP tab (chrome://, about:blank, etc.) — open a new one
    const initialUrl = startingUrl ?? "https://www.google.com";
    tab = await chrome.tabs.create({ url: initialUrl, active: true });
    await sleep(1500);
    needsNavigate = false; // already at startingUrl (or google as default)
  }

  if (!tab.id) throw new Error("No usable tab");
  activeTabId = tab.id;
  tabStack    = [];
  stepIndex   = 0;
  void persistSession();

  // Re-query to get live title — the tab object from create/query may be stale
  const liveTab = await chrome.tabs.get(tab.id);
  notifyUi({ type: "tab_event", event: { kind: "focused", tabId: tab.id, url: liveTab.url ?? tab.url ?? "", title: liveTab.title ?? tab.title ?? "" } });

  await dbg.attachToTab(tab.id);
  await dbg.sendCommand(tab.id, { method: "Page.enable" });

  if (needsNavigate && startingUrl) {
    await dbg.sendCommand(tab.id, { method: "Page.navigate", params: { url: startingUrl } });
    await sleep(1500);
    notifyUi({ type: "tab_event", event: { kind: "opened", tabId: tab.id, url: startingUrl, title: startingUrl } });
  }

  // Create orchestrator session
  const resp = await fetch(`${serverUrl}/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!resp.ok) throw new Error(`Session create failed: HTTP ${resp.status}`);
  const { session_id, websocket_url } = await resp.json() as { session_id: string; websocket_url: string };
  sessionId = session_id;
  observationSeq = 0;

  const wsUrl = websocket_url.startsWith("ws") ? websocket_url : websocket_url.replace(/^http/, "ws");
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    // ponytail: Bug 4 — successful open resets the reconnect backoff
    // counter. Next time the WS dies we start the delay at 1s again.
    resetReconnectStateOnSuccess();
    // ponytail: Bug 5 — start the ping/pong watchdog.
    startHeartbeat();
    ws!.send(JSON.stringify({
      type: "task_start",
      task: goal,
      session_id,
      user_policy: userPolicy,
    }));
  };

  ws.onmessage = async (ev) => {
    if (!activeTabId) return;
    const msg = JSON.parse(ev.data as string) as any;
    const tid = activeTabId;

    switch (msg.type) {
      case "observe":
        await sendObservation(tid);
        break;

      case "action":
        await executeAction(tid, msg.action);
        await sendObservation(tid);
        break;

      case "step_progress":
        notifyUi({
          type:        "step_card",
          index:       stepIndex++,
          title:       msg.action ?? "",
          clientText:  msg.thought ?? msg.reasoning ?? "",
          reasoning:   msg.reasoning ?? "",
          result:      "",
          url:         msg.url ?? "",
          pageTitle:   "",
          actionTarget: msg.action_target ?? null,
          actions:     Array.isArray(msg.actions) ? msg.actions : [],
          iconKind:    msg.action ?? "navigate",
          ts:          Date.now(),
          context:     msg.context ?? null,
        });
        notifyUi({ type: "canonical_status", status: "executing" });
        break;

      case "pong":
        // ponytail: Bug 5 — heartbeat response. Reset the deadline so the
        // next ping has a fresh 30s window. If pong stops arriving, the
        // interval callback in startHeartbeat() force-closes the WS.
        lastPongAt = Date.now();
        break;

      case "context_update":
        // ponytail: step had no external actions (e.g. scratchpad-only).
        // Still emit context so the sidepanel utilization % updates on
        // every step, not just on visible UI bubbles.
        notifyUi({
          type:    "context_update",
          context: msg.context ?? null,
        });
        break;

      case "task_result": {
        if (taskTerminalEmitted) break;
        taskTerminalEmitted = true;
        taskInFlight = false;
        void setBadge(false);
        const r = msg.result ?? {};
        if (r.status === "completed") {
          notifyUi({ type: "task_completed", summary: r.summary ?? "", steps: stepIndex, finalAnswer: r.summary ?? "", extracted_data: r.extracted_data, timing: r.timing ?? null });
          notifyUi({ type: "canonical_status", status: "completed" });
        } else {
          // ponytail: field names match the sidepanel's task_failed
          // handler. Earlier payload used `code` + `message` which made
          // renderPolicyFailureCard's `message.failure_reason` lookup
          // miss, so the generic "Task failed" fallback rendered even
          // for policy_preflight. `failure_reason` and `summary` are
          // what the renderer branches on.
          notifyUi({
            type: "task_failed",
            failure_reason: r.failure_reason ?? r.status ?? "failed",
            summary: r.summary ?? "Task failed",
            timing: r.timing ?? null,
          });
          notifyUi({ type: "canonical_status", status: "failed" });
        }
        break;
      }

      case "task_error":
        if (taskTerminalEmitted) break;
        taskTerminalEmitted = true;
        taskInFlight = false;
        void setBadge(false);
        // ponytail: failure_reason + summary field names — see the
        // matching note on the task_result handler.
        notifyUi({ type: "task_failed", failure_reason: "TASK_ERROR", summary: msg.error ?? "Unknown error" });
        notifyUi({ type: "canonical_status", status: "failed" });
        break;

      case "ask_human": {
        const id = newId("clarify");
        pendingClarifyResolvers.set(id, (answer) => {
          ws?.send(JSON.stringify({ type: "human_reply", content: answer }));
          currentPrompt = null;
          void persistSession();
        });
        currentPrompt = "clarify";
        void persistSession();
        notifyUi({ type: "clarify_request", id, question: msg.question ?? "", reason: "" });
        break;
      }

      case "approval_required": {
        const id = newId("approval");
        pendingApprovalResolvers.set(id, (approved) => {
          ws?.send(JSON.stringify({ type: "human_reply", content: approved ? "yes" : "no" }));
          currentPrompt = null;
          void persistSession();
        });
        currentPrompt = "approval";
        void persistSession();
        notifyUi({
          type: "approval_request", id,
          reason: msg.reasoning ?? "The agent wants to perform a sensitive action.",
          action: { type: msg.action, url: msg.args?.url },
        });
        break;
      }

      case "login_required": {
        let domain = "";
        try { domain = new URL(msg.message ?? "").hostname; } catch { domain = "this site"; }
        waitingForLogin = true;
        currentPrompt = "login";
        void persistSession();
        notifyUi({ type: "login_required", url: msg.message ?? "", domain });
        break;
      }

      case "stagnation_warning":
        notifyUi({ type: "stagnation_warning", reason: msg.reason ?? "" });
        break;

      case "evaluate": {
        try {
          const r = await dbg.sendCommand(tid, {
            method: "Runtime.evaluate",
            params: { expression: msg.expression ?? "''", returnByValue: true },
          }) as { result?: { value?: unknown } };
          ws!.send(JSON.stringify({ type: "evaluate_result", value: String(r.result?.value ?? "") }));
        } catch (e) {
          ws!.send(JSON.stringify({ type: "evaluate_result", value: "", error: String(e) }));
        }
        break;
      }
    }
  };

  ws.onerror = () => {
    if (!taskTerminalEmitted) {
      taskTerminalEmitted = true;
      taskInFlight = false;
      void setBadge(false);
      // ponytail: failure_reason + summary field names — see the
      // matching note on the task_result handler.
      notifyUi({ type: "task_failed", failure_reason: "WS_ERROR", summary: "WebSocket connection error" });
      notifyUi({ type: "canonical_status", status: "failed" });
    }
  };

  ws.onclose = () => { void cleanup(); };
}

async function cleanup(): Promise<void> {
  const tid = activeTabId;
  // ponytail: WS died mid-task → end the task with a connection-lost
  // reason BEFORE the disconnected event. The harness on the server
  // is stuck waiting on human_input_queue and can't recover from a
  // dead WS, so the only thing we can do from this side is mark the
  // task as failed so the UI stops the timer and shows the bubble.
  // Without this, state.phase stays 'executing' on the sidepanel, the
  // timer keeps running, and the task is effectively invisible-orphan.
  // Reconnect attempts run in the background regardless — they're for
  // the NEXT task.
  if (taskInFlight && !taskTerminalEmitted) {
    taskTerminalEmitted = true;
    taskInFlight = false;
    void setBadge(false);
    notifyUi({
      type: "task_failed",
      failure_reason: "CONNECTION_LOST",
      summary: "Lost connection to the Brotto server. The task can't continue — start a new task once the server is back.",
    });
    notifyUi({ type: "canonical_status", status: "failed" });
  }
  // ponytail: Bug 3 — emit a disconnected event so the sidepanel can
  // update its connection pill. Sent AFTER task_failed so the
  // task_failed handler runs first and the pill update doesn't race
  // with the terminal phase set.
  notifyUi({ type: "disconnected", reason: "ws_closed" });
  // ponytail: Bug 5 — stop the heartbeat before tearing down ws. The
  // heartbeat interval reads `ws.readyState` and would be a no-op anyway,
  // but explicit stop is easier to reason about.
  stopHeartbeat();
  activeTabId = null;
  tabStack = [];
  ws = null;
  sessionId = null;
  waitingForLogin = false;
  currentPrompt = null;
  lastObservedUrl = "";
  if (tid !== null) void dbg.detachFromTab(tid).catch(() => undefined);
  void setBadge(false);
  void chrome.storage.session.clear();
  // ponytail: Bug 4 — kick off auto-reconnect unless the user clicked
  // Disconnect (their intent is to stay offline).
  scheduleReconnect();
}

// ponytail: Bug 4 — flat-delay reconnect (3 attempts × 5s) for the
// next task. The in-flight task is already terminated by cleanup();
// reconnect is purely so the next `run_local_task` doesn't have to
// wait for the server to come back AND the user to click Connect.
function scheduleReconnect(): void {
  if (userInitiatedDisconnect) return;
  // ponytail: Bug B-fix — only auto-reconnect when a task is actually
  // in flight. After a clean task ending, ws.onclose → cleanup() runs
  // with taskInFlight=false, so reconnect early-returns. This avoids
  // opening ghost WS connections that the server would reject with
  // "expected task_start, got ping" once the 20s heartbeat fires.
  if (!taskInFlight) return;
  if (reconnectTimer !== null) return; // already scheduled
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    notifyUi({ type: "reconnect_giveup" });
    return;
  }
  reconnectAttempts++;
  notifyUi({ type: "reconnect_attempt", attempt: reconnectAttempts, delayMs: BASE_RECONNECT_DELAY_MS });
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    // ponytail: Bug 4 — empty-path WS fix: we used to call
    // `new WebSocket(serverUrl)` where serverUrl is the http:// planner
    // URL, which the browser normalises to ws://host/ (root path). The
    // server's WS endpoints live at /ws/ext/{session_id} and /ws/{user_id}
    // — root is 403. Fix: POST /v1/sessions first to mint a fresh
    // session, then open the WS to the returned websocket_url. The user
    // will need to click Start for the next task — the harness picks
    // up this session via the next startRelay's task_start WS message.
    if (!serverUrl) return;
    void (async () => {
      try {
        const resp = await fetch(`${serverUrl}/v1/sessions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!resp.ok) throw new Error(`session create failed: HTTP ${resp.status}`);
        const { websocket_url } = await resp.json() as { websocket_url: string };
        if (userInitiatedDisconnect) return; // bailed mid-flight
        const probe = new WebSocket(websocket_url);
        probe.onopen = () => {
          if (userInitiatedDisconnect) { try { probe.close(); } catch { /* ignore */ } return; }
          ws = probe;
          resetReconnectStateOnSuccess();
          startHeartbeat();
          notifyUi({ type: "ws_ready" });
        };
        probe.onerror = () => { try { probe.close(); } catch { /* ignore */ } };
        probe.onclose = () => {
          // Probe failed → schedule another attempt. ws.onclose doesn't
          // fire cleanup() here because we haven't reassigned ws yet
          // (the original ws was already nulled by cleanup()).
          void scheduleReconnect();
        };
      } catch (e) {
        console.warn("[brotto] reconnect probe failed:", e);
        // Failure → retry.
        void scheduleReconnect();
      }
    })();
  }, BASE_RECONNECT_DELAY_MS);
}

function cancelReconnect(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  reconnectAttempts = 0;
}

function resetReconnectStateOnSuccess(): void {
  cancelReconnect();
  reconnectAttempts = 0;
  userInitiatedDisconnect = false;
}

function stopRelay(): void {
  taskTerminalEmitted = true;
  ws?.close();
  ws = null;
  const tid = activeTabId;
  activeTabId = null;
  waitingForLogin = false;
  currentPrompt = null;
  if (tid !== null) void dbg.detachFromTab(tid).catch(() => undefined);
  void chrome.storage.session.clear();
}

// ── Message handler ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  void (async () => {
    try {
      switch (message.type) {

        case "run_local_task": {
          if (ws !== null && ws.readyState === WebSocket.OPEN) {
            sendResponse({ success: false, error: "A task is already running" });
            return;
          }
          taskTerminalEmitted = false;
          // ponytail: Bug B-fix — mark a task as in-flight so the
          // auto-reconnect logic only fires for genuine mid-task WS
          // death, not for clean task endings.
          taskInFlight = true;
          pendingClarifyResolvers.clear();
          pendingApprovalResolvers.clear();
          waitingForLogin = false;
          currentPrompt = null;
          lastObservedUrl = "";

          const goal = String(message.task ?? "").trim();
          if (!goal) { sendResponse({ success: false, error: "task is empty" }); return; }

          const stored = await chrome.storage.local.get("settings");
          const plannerUrl: string =
            (message.plannerUrl as string | undefined) ||
            (stored.settings as any)?.serverUrl ||
            DEFAULT_SERVER;

          void setBadge(true);
          notifyUi({ type: "canonical_status", status: "executing" });

          startRelay(goal, plannerUrl, message.startingUrl as string | undefined)
            .catch((err: unknown) => {
              void setBadge(false);
              taskInFlight = false;
              if (!taskTerminalEmitted) {
                taskTerminalEmitted = true;
                // ponytail: failure_reason + summary field names — see
                // the matching note on the task_result handler.
                notifyUi({ type: "task_failed", failure_reason: "START_FAILED", summary: err instanceof Error ? err.message : String(err) });
                notifyUi({ type: "canonical_status", status: "failed" });
              }
            });

          sendResponse({ success: true });
          break;
        }

        case "cancel_local_task": {
          taskTerminalEmitted = true;
          taskInFlight = false;
          stopRelay();
          notifyUi({ type: "canonical_status", status: "cancelled" });
          sendResponse({ success: true });
          break;
        }

        // ponytail: Bug 4 — user clicked Disconnect. Mark intent so
        // auto-reconnect doesn't fight the user; close any in-flight
        // session; the next sidepanel Connect clears the flag and
        // re-allows reconnect.
        case "user_disconnect": {
          userInitiatedDisconnect = true;
          cancelReconnect();
          taskTerminalEmitted = true;
          taskInFlight = false;
          if (ws) {
            try { ws.close(); } catch { /* ignore */ }
          }
          ws = null;
          notifyUi({ type: "canonical_status", status: "disconnected" });
          sendResponse({ success: true });
          break;
        }

        case "local_login_complete": {
          // Manual override for the login pause. The server's harness is
          // blocked on human_input_queue; we push "resume" to unblock it.
          // The next step then re-runs check_login_page on the server.
          signalResume();
          sendResponse({ success: true });
          break;
        }

        case "local_login_skip": {
          taskInFlight = false;
          stopRelay();
          sendResponse({ success: true });
          break;
        }

        case "submit_clarification": {
          const res = pendingClarifyResolvers.get(String(message.id));
          if (res) { pendingClarifyResolvers.delete(String(message.id)); res(String(message.answer ?? "")); }
          sendResponse({ success: true });
          break;
        }

        case "submit_approval": {
          const res = pendingApprovalResolvers.get(String(message.id));
          if (res) { pendingApprovalResolvers.delete(String(message.id)); res(message.approved === true); }
          sendResponse({ success: true });
          break;
        }

        case "reset_session": {
          stopRelay();
          taskTerminalEmitted = false;
          pendingClarifyResolvers.clear();
          pendingApprovalResolvers.clear();
          sendResponse({ success: true });
          break;
        }

        case "get_connection_status":
          sendResponse({ success: true, status: { connected: ws?.readyState === WebSocket.OPEN, session_id: sessionId } });
          break;

        case "policy_changed": {
          // ponytail: write-on-save. The sidepanel already wrote the
          // full settings object to chrome.storage.local; here we just
          // update the in-memory mirror used on the next task_start.
          const s = message.settings as
            | { mode?: string; blacklist?: string[] }
            | undefined;
          if (s) {
            userPolicy = {
              mode: s.mode === "secure" ? "secure" : "normal",
              blacklist: Array.isArray(s.blacklist) ? s.blacklist : [],
            };
          }
          sendResponse({ success: true });
          break;
        }

        case "send_to_server": {
          // ponytail: sidepanel wants to push a message over the active
          // WS to the orchestrator (e.g. policy_acknowledged). Used when
          // there's no task in flight but the user did something the
          // server should know about.
          const payload = message.payload;
          if (ws && ws.readyState === WebSocket.OPEN && payload) {
            ws.send(JSON.stringify(payload));
          }
          sendResponse({ success: true });
          break;
        }

        case "get_user_policy": {
          sendResponse({ success: true, userPolicy });
          break;
        }

        case "get_context": {
          // ponytail: sidepanel asks the backend (via the SW so we
          // proxy through the configured serverUrl) for the model's
          // context window. Backend returns {model, window}; the
          // harness's per-step messages carry the actual usage.
          try {
            const r = await fetch(`${serverUrl}/context`);
            if (!r.ok) {
              sendResponse({ success: false, error: `HTTP ${r.status}` });
              return;
            }
            const data = await r.json();
            sendResponse({ success: true, context: data });
          } catch (e) {
            sendResponse({ success: false, error: e instanceof Error ? e.message : String(e) });
          }
          break;
        }

        default:
          sendResponse({ success: false, error: "Unknown message type" });
      }
    } catch (e) {
      sendResponse({ success: false, error: e instanceof Error ? e.message : String(e) });
    }
  })();
  return true; // keep channel open for async response
});

// ── Tab lifecycle — follow new tabs opened from the active tab ───────────────

chrome.tabs.onCreated.addListener((tab) => {
  if (activeTabId === null || !tab.id) return;
  if (tab.openerTabId !== activeTabId) return; // not from our tab

  const newTabId = tab.id;
  const oldTabId = activeTabId;

  tabStack.push(oldTabId);
  activeTabId = newTabId;

  sleep(400).then(async () => {
    try {
      await dbg.detachFromTab(oldTabId).catch(() => undefined);
      await dbg.attachToTab(newTabId);
      await dbg.sendCommand(newTabId, { method: "Page.enable" });
      notifyUi({ type: "tab_event", event: { kind: "opened", tabId: newTabId, url: tab.url ?? "", title: tab.title ?? "" } });
    } catch (e) {
      console.error("[brotto] failed to attach to new tab:", e);
      activeTabId = oldTabId; // rollback
      tabStack.pop();
    }
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId !== activeTabId) return;
  // Active tab closed — fall back to opener if available
  const fallback = tabStack.pop() ?? null;
  activeTabId = fallback;
  if (fallback !== null) {
    dbg.attachToTab(fallback).then(() =>
      dbg.sendCommand(fallback, { method: "Page.enable" })
    ).catch(() => undefined);
  }
});

// Auto-resume after manual login: when the active tab's URL actually
// changes (top-frame navigation or pushState / title-only update), unblock
// the server's human_input_queue with "resume". The server then re-runs
// check_login_page — if we're still on a login wall, it re-prompts; else
// the agent proceeds. Gate on URL change so SPA title flicker / form
// mutations don't spuriously resume.
chrome.tabs.onUpdated.addListener((_tabId, change, tab) => {
  if (activeTabId === null || _tabId !== activeTabId) return;
  if (!waitingForLogin) return;
  const newUrl = change.url ?? tab.url ?? "";
  if (newUrl && newUrl !== lastObservedUrl) {
    signalResume();
  }
});

// ── Initialise ───────────────────────────────────────────────────────────────

async function initialize(): Promise<void> {
  // Restore any in-flight pause state from the previous SW lifetime.
  await restoreSession();
  // ponytail: Bug 1 — re-hydrate userPolicy from chrome.storage.local
  // so the next task_start ships the saved view, not defaults. Done
  // before restoreSession would otherwise ship empty task_start
  // metadata.
  await hydrateUserPolicy();

  chrome.runtime.onConnect.addListener((port) => {
    if (port.name !== "brotto-sidepanel") return;
    port.onMessage.addListener(() => { /* keep-alive */ });
  });

  chrome.runtime.onInstalled.addListener(() => { void setBadge(false); });

  // Auto-resume after manual login: when the active tab navigates, push a
  // fresh observation AND unblock the server's login wait. Top-frame only —
  // iframes would fire too and add noise.
  if (chrome.webNavigation?.onCommitted) {
    chrome.webNavigation.onCommitted.addListener((details) => {
      if (details.frameId !== 0) return;
      if (activeTabId === null || details.tabId !== activeTabId) return;
      void sendObservation(details.tabId);
      const url = details.url ?? "";
      if (waitingForLogin && url && url !== lastObservedUrl) {
        signalResume();
      }
    });
  }

  try {
    if (chrome.sidePanel?.setPanelBehavior) {
      await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
    }
  } catch { /* Firefox/older Chrome */ }
}

void initialize();
