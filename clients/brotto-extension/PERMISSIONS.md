# Permission Justification Documentation

This document provides detailed justification for each permission requested by the Brotto Browser Extension.

## Permission Overview

| Permission | Justification | Risk Level |
|------------|---------------|------------|
| `debugger` | Core automation capability | High |
| `tabs` | Tab listing for selection | Low |
| `storage` | Persist local settings (server URL) | Low |
| `sidePanel` | Render the side panel UI | Low |
| `<all_urls>` | Access any user-selected website | High |

---

## debugger

### Purpose
The `chrome.debugger` API is the core mechanism for browser automation in this extension.

### Why It's Required
Without this permission, the extension cannot:
- Take screenshots of web pages
- Execute mouse clicks, movements, and scrolls at specific coordinates
- Type text into form fields
- Navigate to URLs
- Read page titles and URLs

### How It's Used
1. User selects a tab for automation
2. Extension calls `chrome.debugger.attach({ tabId })`
3. Extension sends CDP commands through `chrome.debugger.sendCommand`
4. Commands are limited to:
   - `Page.captureScreenshot` - Screenshot capture
   - `Input.dispatchMouseEvent` - Mouse actions (click, move, drag, scroll)
   - `Input.dispatchKeyEvent` - Keyboard actions
   - `Page.navigate` - Navigation
   - `Runtime.evaluate` - Focused text insertion only (no arbitrary JS)
   - `Page.reload` - Page reload
   - `Page.bringToFront` - Focus tab

### Security Controls
- Only attaches to **explicitly user-selected** tabs
- No automatic browser-wide attachment
- Immediate detachment when socket closes
- No support for arbitrary JavaScript execution
- CDP commands are allowlisted, not dynamic

### What It Does NOT Enable
- Access to browser settings
- Access to extensions
- Access to passwords or saved credentials
- Installation of plugins or content
- Modification of browser state beyond the selected tab

---

## tabs

### Purpose
Allows the extension to list available tabs for selection.

### Why It's Required
The tab selection dialog needs to display:
- Open tabs with their titles
- Tab URLs (for security warnings)
- Tab icons (favicons)
- Incognito status

Without this permission, users cannot see which tabs are available to automate.

### How It's Used
- `chrome.tabs.query({ active: true, currentWindow: true })` to find the active tab
- `chrome.tabs.create({ url })` to open a starting tab if the user did not pick one
- `chrome.tabs.get(tabId)` to look up the tab we have attached to
- `chrome.tabs.onCreated` / `chrome.tabs.onRemoved` to keep the side panel's tab bar in sync

### Data Accessed
- `tab.title` - Display name
- `tab.url` - URL for security filtering
- `tab.favIconUrl` - Icon
- `tab.incognito` - Privacy indicator
- `tab.id` - For attachment

### Security Controls
- Only metadata, not page content
- System tabs automatically excluded
- `chrome.tabs.update` / `chrome.tabs.remove` are not called

---

## storage

### Purpose
Persists a small bag of local settings (today: the server URL and any future
user toggles) in `chrome.storage.local`.

### Why It's Required
The extension needs to remember the orchestrator URL between browser
restarts so the user does not have to re-enter it on every reload.

### How It's Used
- `chrome.storage.local.get('settings')` to read the saved server URL
- `chrome.storage.local.set({ settings })` to persist it

### Data Accessed
- One key: `settings`. Stores `{ serverUrl: string }` and a small allow-list
  of feature flags.

### Security Controls
- `chrome.storage.local` only — never `chrome.storage.sync`. Nothing leaves
  the user's machine through this API.
- No PII, no credentials, no automation history.

---

## sidePanel

### Purpose
Lets the extension open its own side panel when the user clicks the toolbar
icon, and route messages between the service worker and the side panel.

### Why It's Required
The side panel is the orchestrator's UI surface — chat, plan, approval,
clarify, status. Without this permission the user would have to open a
separate tab to see what the agent is doing.

### How It's Used
- `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })` once
  at startup so clicking the toolbar icon opens the panel
- `chrome.runtime.sendMessage` from the service worker to push events
  (`step_card`, `task_completed`, `approval_request`, etc.) to the side panel

### Security Controls
- Side panel content is loaded from the extension's own bundle, not from any
  web origin. No third-party scripts.
- No `chrome.sidePanel.setOptions` calls — the panel is a fixed surface.

---

## \<all_urls\>

### Purpose
Allows the extension to attach debugger to any user-selected website.

### Why It's Required
Users may need to automate any website, including:
- Web applications
- E-commerce sites
- Productivity tools
- Any HTTPS website

Since we cannot predict which sites users will want to automate, we need access to all URLs.

### How It's Used
- User selects a tab from any website
- Extension attaches `chrome.debugger` to that tab
- No automatic access - explicit user selection required

### Security Controls
- **MOST IMPORTANT**: Does NOT automatically access all sites
- User must explicitly select each tab for automation
- Security warnings shown for sensitive sites (banking, email, login)
- Confirmation required before attaching
- Only one tab at a time (or one tab group)
- No silent or background attachment

### Warnings Displayed
The extension warns users before attaching to:
- Banking/financial sites
- Email providers (Gmail, Outlook, etc.)
- Login/authentication pages
- Payment processors (PayPal, Stripe, etc.)
- Sites with "<all_urls>" pattern matches

---

## Data Flow

```
User Action                    Extension Behavior
---------                       ----------------
1. Click icon                  -> Opens side panel (sidePanel)
2. Click "Start Automation"     -> Lists tabs (tabs)
3. Select tab                  -> Checks security (tabs, debugger)
4. Confirm                     -> Attaches debugger (debugger)
5. Automation active           -> Badge turns green (action)
6. Click "Stop"                -> Detaches debugger (debugger)
```

---

## Comparison with Similar Extensions

| Extension | debugger | tabs | all_urls | Notes |
|-----------|-----------|------|----------|-------|
| Vimium | No | Yes | Yes | Keyboard navigation |
| Momentum | No | Yes | Yes | New tab page |
| LastPass | No | Yes | Yes | Password manager |
| This Extension | Yes | Yes | Yes | Browser automation |

---

## Privacy Considerations

### What We DON'T Access
- Browser history
- Bookmarks
- Passwords or credentials
- Cookies directly (only through CDP which is logged)
- Extension data from other extensions
- System files

### What We DO Access
- Tab titles and URLs (for display and security)
- Screenshots (sent to server only during automation)
- Mouse/keyboard events (during automation only)

### Data Transmission
- All data sent only to configured Brotto server
- Screenshots transmitted via encrypted WSS relay
- No third-party analytics or tracking

---

## User Consent

The extension implements multiple layers of user consent:

1. **Installation Consent**: Chrome Web Store displays all permissions before installation
2. **Pairing Consent**: User must enter pairing code to connect to server
3. **Tab Selection Consent**: User explicitly selects which tab to automate
4. **Security Warning Consent**: Users see warnings for sensitive sites and must confirm
5. **Session Start Consent**: Users must actively start automation
6. **Session End Control**: Users can stop automation at any time via popup or badge

---

## Chrome Web Store Compliance

This extension follows Chrome Web Store policies:

1. **Limited Use Policy**: Only requests permissions necessary for functionality
2. **Prominent Disclosure**: All permissions and their purposes are clearly documented
3. **No Surprising Features**: Extension does not do anything unexpected
4. **User Control**: All actions require explicit user consent
5. **Data Handling**: No personal data is collected or transmitted except as part of automation

---

## Conclusion

The permissions requested by this extension are:
- **Necessary**: Required for the stated functionality
- **Minimal**: Only what's required for browser automation
- **Controlled**: All access requires explicit user consent
- **Transparent**: All permissions and their uses are documented

The extension follows the principle of least privilege by:
- Using debugger commands only from an allowlist
- Attaching only to explicitly selected tabs
- Immediately detaching when sessions end
- Not storing or transmitting data beyond the automation session
