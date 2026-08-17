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
let taskTerminalEmitted = false;
let stepIndex = 0;

const pendingClarifyResolvers  = new Map<string, (answer: string) => void>();
const pendingApprovalResolvers = new Map<string, (approved: boolean) => void>();
let reqCounter = 0;
function newId(prefix: string) { return `${prefix}-${Date.now().toString(36)}-${++reqCounter}`; }

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
    ws.send(JSON.stringify({ type: "observation", ...obs }));
    // Keep tab bar in sync with every navigation within the active tab
    notifyUi({ type: "tab_event", event: { kind: "navigated", tabId, url: obs.url, title: obs.title } });
  } catch (e) {
    ws.send(JSON.stringify({ type: "observation_error", error: String(e) }));
  }
}

// ── Main relay ───────────────────────────────────────────────────────────────

async function startRelay(goal: string, serverUrl: string, startingUrl?: string): Promise<void> {
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

  const wsUrl = websocket_url.startsWith("ws") ? websocket_url : websocket_url.replace(/^http/, "ws");
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    ws!.send(JSON.stringify({ type: "task_start", task: goal, session_id }));
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
          iconKind:    msg.action ?? "navigate",
          ts:          Date.now(),
        });
        notifyUi({ type: "canonical_status", status: "executing" });
        break;

      case "task_result": {
        if (taskTerminalEmitted) break;
        taskTerminalEmitted = true;
        void setBadge(false);
        const r = msg.result ?? {};
        if (r.status === "completed") {
          notifyUi({ type: "task_completed", summary: r.summary ?? "", steps: stepIndex, finalAnswer: r.summary ?? "", extracted_data: r.extracted_data });
          notifyUi({ type: "canonical_status", status: "completed" });
        } else {
          notifyUi({ type: "task_failed", code: r.failure_reason ?? r.status ?? "failed", message: r.summary ?? "Task failed" });
          notifyUi({ type: "canonical_status", status: "failed" });
        }
        break;
      }

      case "task_error":
        if (taskTerminalEmitted) break;
        taskTerminalEmitted = true;
        void setBadge(false);
        notifyUi({ type: "task_failed", code: "TASK_ERROR", message: msg.error ?? "Unknown error" });
        notifyUi({ type: "canonical_status", status: "failed" });
        break;

      case "ask_human": {
        const id = newId("clarify");
        pendingClarifyResolvers.set(id, (answer) => {
          ws?.send(JSON.stringify({ type: "human_reply", content: answer }));
        });
        notifyUi({ type: "clarify_request", id, question: msg.question ?? "", reason: "" });
        break;
      }

      case "approval_required": {
        const id = newId("approval");
        pendingApprovalResolvers.set(id, (approved) => {
          ws?.send(JSON.stringify({ type: "human_reply", content: approved ? "yes" : "no" }));
        });
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
      void setBadge(false);
      notifyUi({ type: "task_failed", code: "WS_ERROR", message: "WebSocket connection error" });
      notifyUi({ type: "canonical_status", status: "failed" });
    }
  };

  ws.onclose = () => { void cleanup(); };
}

async function cleanup(): Promise<void> {
  const tid = activeTabId;
  activeTabId = null;
  tabStack = [];
  ws = null;
  sessionId = null;
  if (tid !== null) void dbg.detachFromTab(tid).catch(() => undefined);
  void setBadge(false);
}

function stopRelay(): void {
  taskTerminalEmitted = true;
  ws?.close();
  ws = null;
  const tid = activeTabId;
  activeTabId = null;
  if (tid !== null) void dbg.detachFromTab(tid).catch(() => undefined);
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
          pendingClarifyResolvers.clear();
          pendingApprovalResolvers.clear();

          const goal = String(message.task ?? "").trim();
          if (!goal) { sendResponse({ success: false, error: "task is empty" }); return; }

          const stored = await chrome.storage.local.get("settings");
          const serverUrl: string =
            (message.plannerUrl as string | undefined) ||
            (stored.settings as any)?.serverUrl ||
            DEFAULT_SERVER;

          void setBadge(true);
          notifyUi({ type: "canonical_status", status: "executing" });

          startRelay(goal, serverUrl, message.startingUrl as string | undefined)
            .catch((err: unknown) => {
              void setBadge(false);
              if (!taskTerminalEmitted) {
                taskTerminalEmitted = true;
                notifyUi({ type: "task_failed", code: "START_FAILED", message: err instanceof Error ? err.message : String(err) });
                notifyUi({ type: "canonical_status", status: "failed" });
              }
            });

          sendResponse({ success: true });
          break;
        }

        case "cancel_local_task": {
          taskTerminalEmitted = true;
          stopRelay();
          notifyUi({ type: "canonical_status", status: "cancelled" });
          sendResponse({ success: true });
          break;
        }

        case "local_login_complete": {
          if (activeTabId !== null) void sendObservation(activeTabId);
          sendResponse({ success: true });
          break;
        }

        case "local_login_skip": {
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

// ── Initialise ───────────────────────────────────────────────────────────────

async function initialize(): Promise<void> {
  chrome.runtime.onConnect.addListener((port) => {
    if (port.name !== "brotto-sidepanel") return;
    port.onMessage.addListener(() => { /* keep-alive */ });
  });

  chrome.runtime.onInstalled.addListener(() => { void setBadge(false); });

  try {
    if (chrome.sidePanel?.setPanelBehavior) {
      await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
    }
  } catch { /* Firefox/older Chrome */ }
}

void initialize();
