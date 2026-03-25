// SECURITY: externally_connectable in manifest.json restricts which origins can send
// SET_AUTH_TOKEN messages. Only the listed frontend origins are allowed. Without that
// manifest entry, any website could inject a fake JWT into this extension.

// Also update manifest.json host_permissions and externally_connectable matches.
const API_BASE = "https://job-tracker-v2-kappa.vercel.app/api";

// ─── URL HELPERS ─────────────────────────────────────────────────────────────

const APPLY_RE = /^https?:\/\/[^/]*\.(myworkdayjobs|myworkday|myworkdaysite)\.com\/.*\/job\/.*\/apply(\/|$)/;
const COMPLETION_RE = /\/jobTasks\/completed\/application/;

function isApplyUrl(url) {
  return APPLY_RE.test(url);
}

function isCompletionUrl(url) {
  return COMPLETION_RE.test(url);
}

/**
 * Extract job info from a Workday /apply/ URL.
 * e.g. https://meredith.wd5.myworkdayjobs.com/en-US/careers/job/London/Warehouse-Worker_JR26-27660/apply/applyManually
 * → { jobId: "Warehouse-Worker_JR26-27660", sourceUrl: "https://...job/London/Warehouse-Worker_JR26-27660" }
 */
function extractJobInfoFromUrl(url) {
  const applyIdx = url.indexOf("/apply");
  if (applyIdx === -1) return null;
  const sourceUrl = url.substring(0, applyIdx);
  // Job ID is the last path segment before /apply/
  const pathBeforeApply = new URL(sourceUrl).pathname;
  const segments = pathBeforeApply.split("/").filter(Boolean);
  // The job ID follows /job/{location}/ — it's the segment after "job" + location
  const jobIdx = segments.indexOf("job");
  // Take the last segment before /apply as the job ID (covers variable path depth)
  const jobId = segments.length > 0 ? segments[segments.length - 1] : null;
  return { jobId, sourceUrl };
}

/**
 * Extract company name from Workday URL subdomain.
 * e.g. "meredith.wd5.myworkdayjobs.com" → "Meredith"
 */
function companyFromUrl(url) {
  try {
    const hostParts = new URL(url).hostname.split(".");
    if (hostParts.length > 1 && !/^wd\d+$/i.test(hostParts[0])) {
      return hostParts[0].charAt(0).toUpperCase() + hostParts[0].slice(1);
    }
  } catch {}
  return "Unknown";
}

/**
 * Extract role name from job ID slug.
 * e.g. "Warehouse-Worker_JR26-27660" → "Warehouse Worker"
 */
function roleFromUrl(jobId) {
  if (!jobId) return "Unknown Role";
  // Strip trailing R-number pattern (e.g. _JR26-27660, _R2000648316)
  const cleaned = jobId.replace(/_?[A-Z]?R\d[\d-]*$/, "");
  return cleaned.replace(/[-_]/g, " ").trim() || "Unknown Role";
}

// ─── API CALL HELPER ─────────────────────────────────────────────────────────

/**
 * Authenticated POST to the backend. Returns { success, data, error }.
 * Clears auth token on 401.
 */
async function apiCall(endpoint, payload) {
  const { auth_token } = await chrome.storage.session.get("auth_token");
  if (!auth_token) {
    return { success: false, data: null, error: "not_authenticated" };
  }
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${auth_token}`
      },
      body: JSON.stringify(payload)
    });

    if (response.status === 401) {
      await chrome.storage.session.remove("auth_token");
      return { success: false, data: null, error: "token_expired" };
    }

    const data = await response.json();
    return { success: response.ok, data, error: response.ok ? null : data?.detail };
  } catch (err) {
    return { success: false, data: null, error: err.message };
  }
}

// ─── MESSAGE LISTENERS ───────────────────────────────────────────────────────

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
    (async () => {
      const result = await apiCall("/extension/capture", message.payload);
      sendResponse(result);
    })();
    return true; // keep channel open for async response
  }
});

// ─── TAB NAVIGATION LISTENER ────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) return;
  const url = changeInfo.url;

  // /apply/ navigation — auto-capture IN_PROGRESS + hide overlay
  if (isApplyUrl(url)) {
    const info = extractJobInfoFromUrl(url);
    if (!info) return;

    // Store tab state in chrome.storage.session (survives MV3 service worker restarts)
    const tabKey = `tab_${tabId}`;
    chrome.storage.session.set({ [tabKey]: { jobId: info.jobId, sourceUrl: info.sourceUrl } });

    // Try to get full capture data from content script (may still be alive from /job/ page)
    chrome.tabs.sendMessage(tabId, { type: "GET_CAPTURE_DATA" })
      .then(async (captureData) => {
        // Content script responded — use cached data with the correct source_url
        await apiCall("/extension/capture", {
          company_name: captureData.company_name,
          role: captureData.role,
          job_description: captureData.job_description,
          source_url: info.sourceUrl,
          ats_job_id: captureData.ats_job_id || info.jobId,
        });
      })
      .catch(async () => {
        // Content script not available — fall back to URL parsing
        await apiCall("/extension/capture", {
          company_name: companyFromUrl(url),
          role: roleFromUrl(info.jobId),
          source_url: info.sourceUrl,
          ats_job_id: info.jobId,
        });
      });

    // Hide overlay (existing behavior)
    chrome.tabs.sendMessage(tabId, { type: "HIDE_OVERLAY" }).catch(() => {});
    return;
  }

  // Completion URL — mark APPLIED
  if (isCompletionUrl(url)) {
    const tabKey = `tab_${tabId}`;
    chrome.storage.session.get(tabKey).then(async (stored) => {
      const state = stored[tabKey];
      if (!state) {
        // No stored state — user navigated directly to completion URL, no-op
        console.log("[job-tracker-v2] completion URL with no tab state, skipping");
        return;
      }
      await apiCall("/extension/applied", {
        source_url: state.sourceUrl,
        ats_job_id: state.jobId,
      });
      // Clear tab state regardless of outcome
      chrome.storage.session.remove(tabKey);
    });
    return;
  }
});

// ─── TAB CLEANUP ─────────────────────────────────────────────────────────────

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab_${tabId}`);
});
