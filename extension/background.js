// SECURITY: externally_connectable in manifest.json restricts which origins can send
// SET_AUTH_TOKEN messages. Only the listed frontend origins are allowed. Without that
// manifest entry, any website could inject a fake JWT into this extension.

// Also update manifest.json host_permissions and externally_connectable matches.
const API_BASE = "https://job-tracker-v2-kappa.vercel.app/api";

// ─── SESSION STORAGE ACCESS ─────────────────────────────────────────────────
// By default, chrome.storage.session is only accessible from trusted contexts
// (background script, popup). Content scripts need TRUSTED_AND_UNTRUSTED_CONTEXTS
// to read/write session storage for caching job data.
chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" });

// ─── URL HELPERS ─────────────────────────────────────────────────────────────

/**
 * Normalize a source URL for dedup: strip query params, hash, trailing slash.
 * Both content.js manual capture and background.js auto-capture must produce
 * the same normalized URL for the same job posting.
 */
function normalizeSourceUrl(url) {
  try {
    const u = new URL(url);
    let normalized = u.origin + u.pathname;
    // Strip trailing slash (unless root "/")
    if (normalized.length > u.origin.length + 1 && normalized.endsWith("/")) {
      normalized = normalized.slice(0, -1);
    }
    return normalized;
  } catch {
    return url;
  }
}

const APPLY_RE = /^https?:\/\/[^/]*\.(myworkdayjobs|myworkday|myworkdaysite)\.com\/.*\/(?:job|details)\/.*\/apply(\/|$)/;
const COMPLETION_RE = /\/jobTasks\/completed\/application/;

function isApplyUrl(url) {
  return APPLY_RE.test(url);
}

function isCompletionUrl(url) {
  return COMPLETION_RE.test(url);
}

/**
 * Extract job info from a Workday /apply/ URL.
 * Supports both /job/ and /details/ path patterns:
 * e.g. https://meredith.wd5.myworkdayjobs.com/en-US/careers/job/London/Warehouse-Worker_JR26-27660/apply
 * e.g. https://bmo.wd3.myworkdayjobs.com/en-US/External/details/Software-Developer_R260004443-1/apply
 * → { jobId: "...", sourceUrl: "https://...{path-before-apply}" }
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

// No internal message listeners — auto-capture is handled entirely by
// tabs.onUpdated detecting /apply/ navigation. The "Track it" button has
// been removed; content.js caches data to chrome.storage.session instead.

// ─── OVERLAY INJECTION ──────────────────────────────────────────────────────

/**
 * Inject a passive status overlay into the given tab.
 * Uses chrome.scripting.executeScript so it works even when no content script
 * is injected (e.g. on /apply/ or completion pages).
 * @param {number} tabId
 * @param {string} message - Text to display (e.g. "Tracking this application…")
 * @param {string} [color="#0f172a"] - CSS color for the message text
 */
function injectTrackingOverlay(tabId, message, color = "#0f172a") {
  chrome.scripting.executeScript({
    target: { tabId },
    func: (msg, clr) => {
      if (document.getElementById("jt-overlay")) return; // already visible
      const overlay = document.createElement("div");
      overlay.id = "jt-overlay";
      overlay.style.cssText = [
        "position:fixed",
        "bottom:20px",
        "right:20px",
        "z-index:2147483647",
        "background:#ffffff",
        "border:1px solid #e2e8f0",
        "border-radius:12px",
        "padding:12px 16px",
        "box-shadow:0 8px 24px rgba(0,0,0,0.12)",
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
        "max-width:260px"
      ].join(";");
      overlay.innerHTML =
        '<div style="display:flex;align-items:center;gap:8px;">' +
          '<span style="font-size:14px;">&#9989;</span>' +
          '<p style="margin:0;font-weight:500;font-size:13px;color:' + clr + ';">' + msg + '</p>' +
        '</div>';
      document.body.appendChild(overlay);
      setTimeout(() => overlay.remove(), 3000);
    },
    args: [message, color],
  }).catch(() => {}); // tab may have navigated away
}

// ─── TAB NAVIGATION LISTENER ────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) return;
  const url = changeInfo.url;

  // /apply/ navigation — auto-capture IN_PROGRESS + hide overlay
  if (isApplyUrl(url)) {
    const info = extractJobInfoFromUrl(url);
    if (!info) return;

    const normalizedSource = normalizeSourceUrl(info.sourceUrl);

    // Store tab state for completion detection (survives MV3 service worker restarts)
    const tabKey = `tab_${tabId}`;
    chrome.storage.session.set({ [tabKey]: { jobId: info.jobId, sourceUrl: normalizedSource } });

    // Attempt to read rich data from chrome.storage.session (written by content.js
    // on the /job/{id} page). This is more reliable than messaging the content
    // script, which may be unreachable after SPA navigation.
    const jobKey = `job_${info.jobId}`;
    chrome.storage.session.get(jobKey).then(async (stored) => {
      const cached = stored[jobKey];
      if (cached && cached.company_name) {
        await apiCall("/extension/capture", {
          company_name: cached.company_name,
          role: cached.role,
          job_description: cached.job_description,
          source_url: normalizedSource,
          ats_job_id: cached.ats_job_id || info.jobId,
        });
        chrome.storage.session.remove(jobKey);
        injectTrackingOverlay(tabId, "Tracking this application\u2026");
        return;
      }

      // Fallback: message the content script (may still be alive from /job/ page)
      chrome.tabs.sendMessage(tabId, { type: "GET_CAPTURE_DATA" })
        .then(async (captureData) => {
          await apiCall("/extension/capture", {
            company_name: captureData.company_name,
            role: captureData.role,
            job_description: captureData.job_description,
            source_url: normalizedSource,
            ats_job_id: captureData.ats_job_id || info.jobId,
          });
          injectTrackingOverlay(tabId, "Tracking this application\u2026");
        })
        .catch(async () => {
          // Last resort: extract from URL only (loses JD)
          await apiCall("/extension/capture", {
            company_name: companyFromUrl(url),
            role: roleFromUrl(info.jobId),
            source_url: normalizedSource,
            ats_job_id: info.jobId,
          });
          injectTrackingOverlay(tabId, "Tracking this application\u2026");
        });
    });

    // Hide content script overlay if still visible from /job/ page
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
      const result = await apiCall("/extension/applied", {
        source_url: state.sourceUrl,
        ats_job_id: state.jobId,
      });
      if (result.success) {
        injectTrackingOverlay(tabId, "Applied \u2713", "#10b981");
      }
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
