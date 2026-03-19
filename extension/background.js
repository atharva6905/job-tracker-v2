// SECURITY: externally_connectable in manifest.json restricts which origins can send
// SET_AUTH_TOKEN messages. Only the listed frontend origins are allowed. Without that
// manifest entry, any website could inject a fake JWT into this extension.

// TODO: Replace with production HTTPS URL before deploying.
// Also update manifest.json host_permissions and externally_connectable matches.
const API_BASE = "http://localhost:8000";

// Listen for messages from the frontend (restricted to externally_connectable origins)
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (message.type === "SET_AUTH_TOKEN") {
    chrome.storage.session.set({ auth_token: message.token }, () => {
      sendResponse({ success: true });
    });
    return true; // keep channel open for async response
  }
  if (message.type === "PING") {
    sendResponse({ pong: true });
    return true;
  }
});

// Listen for capture requests from content.js
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "CAPTURE_APPLICATION") {
    chrome.storage.session.get("auth_token", async ({ auth_token }) => {
      if (!auth_token) {
        sendResponse({ success: false, error: "not_authenticated" });
        return;
      }
      try {
        const response = await fetch(`${API_BASE}/extension/capture`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${auth_token}`
          },
          body: JSON.stringify(message.payload)
        });

        if (response.status === 401) {
          await chrome.storage.session.remove("auth_token");
          sendResponse({ success: false, error: "token_expired" });
          return;
        }

        const data = await response.json();
        sendResponse({ success: response.ok, data, error: response.ok ? null : data?.detail });
      } catch (err) {
        sendResponse({ success: false, error: err.message });
      }
    });
    return true; // keep channel open for async response
  }
});
