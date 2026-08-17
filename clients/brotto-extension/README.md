# Brotto Browser Extension

Chrome/Edge extension that enables selected browser tabs to be controlled by the Brotto automation platform using `chrome.debugger`.

## Purpose

The browser extension provides:
- Connection of selected Chrome or Edge tabs to the Brotto server
- Manual tab selection (one tab or tab group per session)
- Explicit `chrome.debugger` attachment with user consent
- Outbound WSS relay connection
- Active badge showing automation status
- Immediate detachment on disconnect
- No remote code execution

## Technology

- TypeScript
- Manifest V3
- WebCrypto for device key generation
- Service worker
- React (popup UI)

## Installation

### From Source

1. Clone the repository
2. Run `npm install` to install dependencies
3. Build with `npm run build`
4. Load the `dist` folder as an unpacked extension in Chrome:
   - Visit `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked"
   - Select the `dist` folder

### Manual Install in Chrome (development)

1. Build the extension:
   ```bash
   pnpm install
   bash scripts/build-extension.sh
   ```
   This produces `build/browser-extension-1.0.0.zip` and a `dist/` folder.

2. Open `chrome://extensions/` in Chrome

3. Enable **Developer mode** (toggle top right)

4. Click **Load unpacked** and select `clients/brotto-extension/dist/`
   - Or drag `clients/brotto-extension/build/browser-extension-1.0.0.zip` onto the extensions page

5. Click the extension icon in the Chrome toolbar to open the popup. Configure the orchestrator server URL (WSS) in the options page.

### From Chrome Web Store (when published)

1. Install from the Chrome Web Store
2. Click the extension icon to get started

## Setup

1. Click the Brotto extension icon in your browser toolbar
2. Enter your server URL (provided by your administrator)
3. Click "Start Pairing" to begin device registration
4. Enter the 8-character pairing code from the server
5. Your device is now paired

## Usage

### Starting Automation

1. Click the Brotto extension icon
2. Click "Start Automation"
3. Select a tab to automate (or select a tab group)
4. Review any security warnings
5. Click "Attach to Tab"
6. The badge will turn green showing "ON"

### Stopping Automation

1. Click the Brotto extension icon
2. Click "Stop Automation"
3. The session ends and debugger detaches

### Disconnecting

1. Click the extension icon
2. Click "Logout" to unpair the device

## Permissions

This extension requires the following permissions with detailed justifications:

### `debugger`

**Purpose:** Core browser automation capability

**Justification:** The `chrome.debugger` API is the mechanism for browser automation. It enables:
- Taking screenshots of the selected tab
- Executing mouse clicks, movements, and scrolls at specific coordinates
- Typing text into focused elements
- Navigating to URLs
- Reading page information

Without this permission, the extension cannot automate browser tasks. The extension only uses debugger commands that are necessary for browser automation and does not execute arbitrary JavaScript.

**CDP Commands Used:**
- `Page.captureScreenshot`
- `Input.dispatchMouseEvent`
- `Input.dispatchKeyEvent`
- `Page.navigate`
- `Runtime.evaluate` (for focused text insertion only)

### `activeTab`

**Purpose:** Access the user's selected tab

**Justification:** When the user explicitly clicks the extension icon or selects a tab for automation, the `activeTab` permission allows the extension to communicate with that tab. This is a standard Chrome permission that:
- Only activates when the user invokes the extension
- Does not grant access to tabs in the background
- Automatically expires when the user navigates away from the tab

### `tabs`

**Purpose:** List available tabs for selection

**Justification:** The extension needs to display a list of open tabs so users can choose which one to automate. This permission:
- Only provides tab titles and URLs, not tab contents
- Requires user action to display the list
- Does not grant the ability to modify or control tabs

### `tabGroups`

**Purpose:** Work with Chrome tab groups

**Justification:** Users may organize their tabs into groups. This permission allows:
- Displaying tab groups in the selection dialog
- Managing group associations during automation
- One tab group per automation session (per architecture requirements)

### `<all_urls>`

**Purpose:** Attach debugger to any user-selected website

**Justification:** Users may need to automate any website. This is a standard permission for debugger extensions because:
- The extension does NOT automatically access all sites
- Users must explicitly select each tab for automation
- The extension cannot silently attach to tabs
- A clear warning is shown before attaching to authenticated/secure sites

**Security Notes:**
- The extension shows warnings for sensitive sites (banking, email, login pages)
- Users must confirm before attaching to any tab
- Only the explicitly selected tab is attached
- No browser-wide or silent attachment

## Security Features

### No Remote Code Execution

This extension deliberately does NOT:
- Execute arbitrary JavaScript from the server
- Use `eval()` or similar functions
- Accept code commands through the relay
- Download or run external scripts

All automation commands are pre-defined CDP operations (screenshot, click, type, navigate) that are explicitly allowed and audited.

### Token Management

- Device keys generated using WebCrypto
- Private keys are non-exportable where supported
- Short-lived session tokens
- Single-use pairing codes
- Server-side token revocation
- No permanent API tokens in storage

### Session Controls

- One tab group per automation session
- No automatic reconnection after explicit cancellation
- Immediate debugger detachment when socket closes
- Manual tab selection required
- No silent browser-wide attachment

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Browser                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │   Popup     │  │  Tab being   │  │  Content   │  │
│  │  (UI)       │  │  automated   │  │  Script    │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬─────┘  │
│         │                │                  │        │
│         └────────────────┼──────────────────┘        │
│                          │                           │
│  ┌───────────────────────▼────────────────────────┐ │
│  │         Background Service Worker               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────────────┐   │ │
│  │  │ Debugger│ │  Relay  │ │    Crypto      │   │ │
│  │  │ Manager │ │ Client  │ │    (Keys)      │   │ │
│  │  └────┬────┘ └────┬────┘ └────────┬────────┘   │ │
│  └───────┼───────────┼───────────────┼─────────────┘ │
└──────────┼───────────┼───────────────┼───────────────┘
           │           │               │
           │    chrome.debugger       │
           │           │               │
           └───────────┼───────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  WSS Relay      │
              │  (Outbound)     │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Brotto Server │
              │  (Control Plane)│
              └─────────────────┘
```

## Files

```
browser-extension/
├── manifest.json        # Extension manifest (MV3)
├── README.md            # This file
├── src/
│   ├── background.ts     # Service worker
│   ├── background.js     # Compiled service worker
│   ├── content.ts       # Content script
│   ├── content.js       # Compiled content script
│   ├── popup.tsx        # React popup component
│   ├── popup.html       # Popup HTML
│   ├── popup.js         # Compiled popup
│   ├── tab-selector.tsx # Tab selection component
│   ├── options.ts       # Options page logic
│   ├── options.html     # Options page HTML
│   ├── options.js       # Compiled options
│   ├── debugger.ts      # chrome.debugger wrapper
│   ├── relay.ts         # WebSocket relay client
│   ├── crypto.ts        # WebCrypto device keys
│   └── pairing.ts       # Device pairing flow
├── tests/
│   └── *.test.ts        # Unit tests
└── icons/
    └── *.png            # Extension icons
```

## Browser Compatibility

- Chrome 88+ (Manifest V3 support)
- Edge 88+ (Chromium-based)
- Other Chromium browsers may work but are not officially supported

## Limitations

- Higher-risk interactive mode (accesses user's logged-in browser state)
- `chrome.debugger` exposes only supported CDP domains
- Service workers can be suspended (background service worker limitations)
- Extension behavior may vary between Chrome and Edge versions
- Window size and viewport cannot always be controlled consistently
- Browser updates can change debugger behavior
- Chrome Web Store review may scrutinize `<all_urls>` and debugger permissions

## Troubleshooting

### Extension not connecting

1. Check that the server URL is correct
2. Verify your device is still paired
3. Check that the relay server is accessible
4. Try re-pairing the device

### Tab not automating

1. Ensure you selected the correct tab
2. Check that the tab is not a system tab (chrome://, etc.)
3. Try refreshing the tab before selecting it
4. Check for any security warnings

### Service worker issues

Chrome may suspend the service worker after periods of inactivity. If automation stops unexpectedly:
1. Click the extension icon to wake the service worker
2. Restart the automation session

## Privacy

- The extension only accesses tabs explicitly selected by the user
- Screenshots are sent to the configured Brotto server only
- No data is sent to third parties
- Session data is not retained after disconnection
- See the main Brotto platform privacy policy for server-side data handling

## Support

For issues and feature requests, please contact your administrator or file an issue in the project repository.

## License

Apache-2.0
