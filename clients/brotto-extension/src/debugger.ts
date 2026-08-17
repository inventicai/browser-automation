/**
 * chrome.debugger wrapper for tab attachment and detachment
 * Handles all CDP-related operations with proper cleanup
 */

export interface DebuggerSession {
  sessionId: string;
  tabId: number;
  attachedAt: number;
  debuggerUrl: string;
}

export interface CdpCommand {
  method: string;
  params?: Record<string, unknown>;
}

export interface CdpEvent {
  method: string;
  params?: Record<string, unknown>;
}

export type CdpEventHandler = (event: CdpEvent) => void;

const DEBUGGER_TARGETS = new Map<string, DebuggerSession>();

let eventHandlers: Map<string, CdpEventHandler[]> = new Map();

/**
 * Attach chrome.debugger to a specific tab
 */
export async function attachToTab(tabId: number): Promise<DebuggerSession> {
  const debuggerUrl = `ws://localhost/${tabId}`;

  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, "1.3", async () => {
      const lastError = chrome.runtime.lastError;
      if (lastError) {
        reject(new Error(`Failed to attach: ${lastError.message}`));
        return;
      }

      const session: DebuggerSession = {
        sessionId: `${tabId}-${Date.now()}`,
        tabId,
        attachedAt: Date.now(),
        debuggerUrl
      };

      DEBUGGER_TARGETS.set(session.sessionId, session);
      resolve(session);
    });
  });
}

/**
 * Detach chrome.debugger from a specific tab
 */
export async function detachFromTab(tabId: number): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.debugger.detach({ tabId }, () => {
      const lastError = chrome.runtime.lastError;
      if (lastError) {
        // Not a critical error - tab might already be closed
        console.warn(`Detach warning: ${lastError.message}`);
      }

      // Clean up any session for this tab
      for (const [sessionId, session] of DEBUGGER_TARGETS.entries()) {
        if (session.tabId === tabId) {
          DEBUGGER_TARGETS.delete(sessionId);
        }
      }

      resolve();
    });
  });
}

/**
 * Detach from all attached tabs
 */
export async function detachAll(): Promise<void> {
  const detachPromises: Promise<void>[] = [];

  for (const session of DEBUGGER_TARGETS.values()) {
    detachPromises.push(detachFromTab(session.tabId));
  }

  await Promise.all(detachPromises);
  DEBUGGER_TARGETS.clear();
}

/**
 * Send a CDP command to an attached tab
 */
export async function sendCommand(
  tabId: number,
  command: CdpCommand
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chrome.debugger.sendCommand as any)({ tabId }, command.method, command.params, (result: unknown, error: unknown) => {
      const lastError = chrome.runtime.lastError;
      if (lastError) {
        reject(new Error(`Command failed: ${lastError.message}`));
        return;
      }
      if (error) {
        reject(new Error(`Command error: ${error}`));
        return;
      }
      resolve(result);
    });
  });
}

/**
 * Get debuggable targets (tabs with debugging URLs)
 */
export function getTargets(): Promise<chrome.debugger.TargetInfo[]> {
  return new Promise((resolve) => {
    chrome.debugger.getTargets((targets) => {
      resolve(targets);
    });
  });
}

/**
 * Get the debugging URL for a tab (WebSocket URL for chrome.debugger)
 */
export function getDebuggerUrl(tabId: number): string {
  return `ws://localhost/${tabId}`;
}

/**
 * Check if debugger is attached to a specific tab
 */
export function isAttached(tabId: number): boolean {
  for (const session of DEBUGGER_TARGETS.values()) {
    if (session.tabId === tabId) {
      return true;
    }
  }
  return false;
}

/**
 * Get active debugger sessions
 */
export function getActiveSessions(): DebuggerSession[] {
  return Array.from(DEBUGGER_TARGETS.values());
}

/**
 * Register an event handler for CDP events from a tab
 */
export function registerEventHandler(tabId: number, eventHandler: CdpEventHandler): void {
  const existingHandlers = eventHandlers.get(`${tabId}`) || [];
  existingHandlers.push(eventHandler);
  eventHandlers.set(`${tabId}`, existingHandlers);

  // Attach the global debugger event listener if this is the first handler
  if (existingHandlers.length === 1) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chrome.debugger.onEvent.addListener as any)(debuggerEventListener);
  }
}

/**
 * Unregister event handlers for a specific tab
 */
export function unregisterEventHandlers(tabId: number): void {
  eventHandlers.delete(`${tabId}`);

  // If no more handlers, remove the global listener
  if (eventHandlers.size === 0) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chrome.debugger.onEvent.removeListener as any)(debuggerEventListener);
  }
}

/**
 * Global CDP event listener - routes events to registered handlers
 */
function debuggerEventListener(source: chrome.debugger.Debuggee, method: string, params?: Record<string, unknown>): void {
  if (!source.tabId) return;

  const handlers = eventHandlers.get(`${source.tabId}`);
  if (!handlers) return;

  const event: CdpEvent = { method, params };

  for (const handler of handlers) {
    try {
      handler(event);
    } catch (err) {
      console.error(`Event handler error for ${method}:`, err);
    }
  }
}

/**
 * Verify that a tab is in a safe state for attachment
 * Shows warnings for authenticated/secure contexts
 */
export async function checkTabSecurity(
  tabId: number
): Promise<{ isSecure: boolean; warnings: string[] }> {
  const warnings: string[] = [];

  try {
    const tab = await chrome.tabs.get(tabId);

    // Check for sensitive URLs
    const sensitivePatterns = [
      /mail\./i,
      /bank/i,
      /paypal/i,
      /stripe/i,
      /coinbase/i,
      /auth\.google/i,
      /login/i,
      /signin/i,
      /account/i
    ];

    const url = tab.url || "";
    for (const pattern of sensitivePatterns) {
      if (pattern.test(url)) {
        warnings.push(`Tab appears to be on a sensitive site: ${url}`);
      }
    }

    // Check for HTTPS
    if (url.startsWith("https://")) {
      // HTTPS is secure
    } else if (url.startsWith("http://")) {
      warnings.push("Tab is not using HTTPS - data may be intercepted");
    }

    // Check incognito
    if (tab.incognito) {
      warnings.push("Tab is in incognito mode");
    }

    return {
      isSecure: warnings.length === 0,
      warnings
    };
  } catch (err) {
    return {
      isSecure: false,
      warnings: [`Could not verify tab security: ${err}`]
    };
  }
}

/**
 * Get tab information relevant for automation
 */
export async function getTabInfo(tabId: number): Promise<{
  id: number;
  title: string;
  url: string;
  favIconUrl: string | undefined;
  incognito: boolean;
  windowId: number;
} | null> {
  try {
    const tab = await chrome.tabs.get(tabId);
    return {
      id: tab.id!,
      title: tab.title || "Untitled",
      url: tab.url || "",
      favIconUrl: tab.favIconUrl,
      incognito: tab.incognito,
      windowId: tab.windowId
    };
  } catch {
    return null;
  }
}
