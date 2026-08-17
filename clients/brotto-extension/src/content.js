/**
 * Content script for the Brotto Browser Extension
 * Injected into pages to provide additional functionality
 * NOTE: This script does NOT enable remote code execution
 */

console.log("Brotto content script loaded");

/**
 * Handle messages from the background script
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log("Content script received message:", message.type);

  switch (message.type) {
    case "get_page_info":
      sendResponse({
        success: true,
        data: {
          title: document.title,
          url: window.location.href,
          readyState: document.readyState,
          visible: isPageVisible()
        }
      });
      break;

    case "ping":
      sendResponse({ success: true, timestamp: Date.now() });
      break;

    default:
      sendResponse({ success: false, error: "Unknown message type" });
  }

  return true;
});

/**
 * Check if the page is visible (not hidden by other tabs/windows)
 */
function isPageVisible() {
  return document.visibilityState === "visible";
}

/**
 * Notify background of visibility changes
 */
document.addEventListener("visibilitychange", () => {
  chrome.runtime.sendMessage({
    type: "page_visibility_changed",
    visible: isPageVisible()
  });
});

/**
 * Notify background of navigation
 */
let lastUrl = window.location.href;
const observer = new MutationObserver(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    chrome.runtime.sendMessage({
      type: "page_navigated",
      url: window.location.href
    });
  }
});

observer.observe(document.body, {
  childList: true,
  subtree: true
});

// Also listen for popstate events (SPA navigation)
window.addEventListener("popstate", () => {
  chrome.runtime.sendMessage({
    type: "page_navigated",
    url: window.location.href
  });
});
