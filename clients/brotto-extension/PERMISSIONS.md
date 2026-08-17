# Permission Justification Documentation

This document provides detailed justification for each permission requested by the Brotto Browser Extension.

## Permission Overview

| Permission | Justification | Risk Level |
|------------|---------------|------------|
| `debugger` | Core automation capability | High |
| `activeTab` | User-initiated tab access | Low |
| `tabs` | Tab listing for selection | Low |
| `tabGroups` | Tab group management | Medium |
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

## activeTab

### Purpose
Allows the extension to access the currently active tab when the user invokes the extension.

### Why It's Required
When the user clicks the extension icon, the extension needs to:
- Display the popup UI
- Potentially communicate with the active tab
- Initiate the tab selection process

### How It's Used
- When popup opens, it queries the active tab
- The activeTab permission grants temporary access to that tab
- Access is automatically revoked when the user navigates away

### Security Controls
- Only activates on **explicit user action** (clicking extension icon)
- Does not grant background tab access
- Automatically scoped to the single active tab
- Does not persist beyond the interaction

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
- `chrome.tabs.query({})` to list all tabs
- Results filtered to exclude system tabs (chrome://, etc.)
- Only displays metadata, does not access tab content

### Data Accessed
- `tab.title` - Display name
- `tab.url` - URL for security filtering
- `tab.favIconUrl` - Icon
- `tab.incognito` - Privacy indicator
- `tab.id` - For attachment

### Security Controls
- Only metadata, not page content
- System tabs automatically excluded
- No ability to modify tabs

---

## tabGroups

### Purpose
Allows the extension to work with Chrome tab groups.

### Why It's Required
Users may organize tabs into groups. This permission enables:
- Displaying tab groups in selection dialog
- Group-based automation (one group per session)
- Managing group associations during automation

### How It's Used
- `chrome.tabGroups.query({})` to list groups
- Group information displayed in tab selector
- Automation attaches to the first tab in selected group

### Security Controls
- Only works with user-created groups
- No ability to create/modify/delete groups
- Single group per automation session (architecture requirement)

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
1. Click icon                  -> Opens popup (activeTab)
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
