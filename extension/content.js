// ─── WORKDAY-ONLY GUARD ───────────────────────────────────────────────────────
// Content script only runs on Workday pages (manifest matches restrict injection,
// but guard as defense-in-depth + meta tag fallback).
const WORKDAY_URL_PATTERNS = [
  /\.wd\d+\.myworkdayjobs\.com/,
  /\.myworkday\.com/,
  /\.myworkdaysite\.com/
];

function isWorkdayPage() {
  const url = window.location.href.toLowerCase();
  if (WORKDAY_URL_PATTERNS.some(p => p.test(url))) return true;
  const meta = document.querySelector('meta[name="application-name"]');
  return meta?.content?.toLowerCase() === "workday";
}

if (!isWorkdayPage() || /\/apply(\/|$)/.test(window.location.pathname) || !/\/job\/[^/]/.test(window.location.pathname)) {
  // Not a Workday job detail page (requires /job/{id}), or on an apply form — exit.
  // No marker, no overlay, no scraping.
  throw new Error("job-tracker-v2: not a Workday job posting page, exiting content script");
}

// Track pending overlay timeouts so SPA navigation can cancel them.
let overlayTimeoutId = null;

function removeOverlayAndCancel() {
  if (overlayTimeoutId !== null) {
    clearTimeout(overlayTimeoutId);
    overlayTimeoutId = null;
  }
  document.getElementById("jt-overlay")?.remove();
}

// ─── EXTENSION DETECTION MARKER ───────────────────────────────────────────────
// Inject a hidden div so the frontend can detect extension installation.
// Frontend (dashboard first-run checklist) checks:
//   document.getElementById("job-tracker-v2-ext")
// Only injected on Workday pages.
const marker = document.createElement("div");
marker.id = "job-tracker-v2-ext";
marker.style.display = "none";
document.body.appendChild(marker);

// ─── JOB ID EXTRACTION ───────────────────────────────────────────────────────
// Extract the job ID segment from a Workday URL path.
// e.g. /en-US/sdm_careers/job/.../Cashier_R2000648316 → "Cashier_R2000648316"
function extractJobId() {
  const match = window.location.pathname.match(/\/job\/([^/?#]+)/);
  return match ? match[1] : null;
}

// ─── JD EXTRACTION ────────────────────────────────────────────────────────────
function extractJobDescription() {
  // SECURITY: ONLY read from structural/display elements — NEVER from form fields.
  // Application forms can contain passwords, SSNs, EEO data, salary info.
  // We must not capture any of that.
  const ALLOWED = "h1, h2, h3, p, li";
  const FORBIDDEN = "input, textarea, select";

  const forbiddenSet = new Set(document.querySelectorAll(FORBIDDEN));

  const allMatched = [...document.querySelectorAll(ALLOWED)]
    .filter(el => {
      // Exclude if the element itself is forbidden
      if (forbiddenSet.has(el)) return false;
      // Exclude if any ancestor is a form field container
      if (el.closest(FORBIDDEN)) return false;
      // Exclude elements inside our own overlay/marker (id starts with "jt-" or "job-tracker-v2-")
      if (el.closest('[id^="jt-"], [id^="job-tracker-v2-"]')) return false;
      return true;
    });

  const matchedSet = new Set(allMatched);

  return allMatched
    .filter(el => {
      // Exclude elements nested inside another matched element (e.g. <p> inside <li>)
      // to prevent textContent duplication — parent already includes child text.
      let parent = el.parentElement;
      while (parent) {
        if (matchedSet.has(parent)) return false;
        parent = parent.parentElement;
      }
      return true;
    })
    .map(el => el.textContent.trim())
    .filter(t => t.length > 20)
    .join("\n")
    .substring(0, 50000); // Hard cap — matches backend ExtensionCaptureRequest.job_description max_length
}

function guessRoleFromPage() {
  const wdHeader = document.querySelector('[data-automation-id="jobPostingHeader"]')?.textContent?.trim();
  const h1 = document.querySelector("h1")?.textContent?.trim() || "";
  const title = document.title || "";
  console.log("[job-tracker-v2] guessRole selectors:", {
    wdHeader: wdHeader || null,
    h1: h1 || null,
    documentTitle: title || null,
  });
  if (wdHeader) return wdHeader.substring(0, 255);
  return (h1 || title).substring(0, 255);
}

function guessCompanyFromPage() {
  const wdCompanyName = document.querySelector('[data-automation-id="jobPostingCompanyName"]')?.textContent?.trim();
  const wdOrgName = document.querySelector('[data-automation-id="organizationName"]')?.textContent?.trim();
  const pathMatch = window.location.pathname.match(/^\/[^/]+\/([^/]+)\/job\//);
  const slug = pathMatch ? pathMatch[1].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : null;
  const titleParts = document.title.split(/[-–|]/);
  const titleFallback = titleParts[titleParts.length - 1]?.trim() || "Unknown";
  console.log("[job-tracker-v2] guessCompany selectors:", {
    wdCompanyName: wdCompanyName || null,
    wdOrgName: wdOrgName || null,
    pathname: window.location.pathname,
    slug: slug || null,
    documentTitle: document.title,
    titleFallback,
  });

  const wdCompany = wdCompanyName || wdOrgName;
  if (wdCompany) return wdCompany.substring(0, 255);

  // Try subdomain — e.g. "meredith" from "meredith.wd5.myworkdayjobs.com"
  const hostParts = window.location.hostname.split(".");
  if (hostParts.length > 1 && !/^wd\d+$/i.test(hostParts[0])) {
    const subdomain = hostParts[0].charAt(0).toUpperCase() + hostParts[0].slice(1);
    return subdomain.substring(0, 255);
  }

  // Only use URL slug if it's longer than 3 chars (avoids "EXT", "US", etc.)
  if (slug && slug.toLowerCase() !== "careers" && slug.length > 3) {
    return slug.substring(0, 255);
  }

  return titleFallback.substring(0, 255);
}

// ─── URL NORMALIZATION ────────────────────────────────────────────────────────
// Must match normalizeSourceUrl in background.js — strip query params, hash,
// trailing slash so manual capture and auto-capture produce identical URLs.
function normalizeSourceUrl(url) {
  try {
    const u = new URL(url);
    let normalized = u.origin + u.pathname;
    if (normalized.length > u.origin.length + 1 && normalized.endsWith("/")) {
      normalized = normalized.slice(0, -1);
    }
    return normalized;
  } catch {
    return url;
  }
}

// ─── CACHED CAPTURE DATA ─────────────────────────────────────────────────────
// Cache extraction results at load time (on the /job/{id} page). When Workday
// SPA navigates to /apply/, the DOM changes but this content script stays alive.
// background.js sends GET_CAPTURE_DATA to retrieve the cached snapshot.
// JD extraction is deferred — Workday loads content dynamically after initial
// render, so extracting immediately at script load often returns empty text.
let _cachedCaptureData = {
  company_name: guessCompanyFromPage(),
  role: guessRoleFromPage(),
  job_description: "",
  source_url: normalizeSourceUrl(window.location.href),
  ats_job_id: extractJobId(),
};

// Defer JD extraction until dynamic content has loaded (same delay as overlay)
setTimeout(() => {
  _cachedCaptureData.job_description = extractJobDescription();
}, 1500);

// ─── OVERLAY ──────────────────────────────────────────────────────────────────
function alreadyShownForJob() {
  const jobId = extractJobId();
  return jobId && sessionStorage.getItem(`jt_shown_${jobId}`) === "1";
}

function markShownForJob() {
  const jobId = extractJobId();
  if (jobId) sessionStorage.setItem(`jt_shown_${jobId}`, "1");
}

function maybeShowOverlay() {
  if (alreadyShownForJob()) return;
  markShownForJob();

  const overlay = document.createElement("div");
  overlay.id = "jt-overlay";
  overlay.style.cssText = [
    "position:fixed",
    "bottom:20px",
    "right:20px",
    "z-index:2147483647", // max z-index — ensures overlay appears above ATS UI
    "background:#ffffff",
    "border:1px solid #e2e8f0",
    "border-radius:12px",
    "padding:16px",
    "box-shadow:0 8px 24px rgba(0,0,0,0.12)",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    "max-width:300px",
    "min-width:240px"
  ].join(";");

  overlay.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <span style="font-size:16px;">📋</span>
      <p style="margin:0;font-weight:600;font-size:14px;color:#0f172a;">Track this application?</p>
    </div>
    <p style="margin:0 0 12px;font-size:12px;color:#64748b;line-height:1.4;">
      job-tracker-v2 will save this to your dashboard automatically.
    </p>
    <div style="display:flex;gap:8px;">
      <button id="jt-confirm" style="flex:1;background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:8px 12px;cursor:pointer;font-size:13px;font-weight:500;">
        Track it
      </button>
      <button id="jt-dismiss" style="flex:1;background:#f1f5f9;color:#475569;border:none;border-radius:6px;padding:8px 12px;cursor:pointer;font-size:13px;">
        Dismiss
      </button>
    </div>
    <p id="jt-status" style="margin:10px 0 0;font-size:12px;color:#64748b;min-height:16px;"></p>
  `;

  document.body.appendChild(overlay);

  document.getElementById("jt-dismiss").onclick = () => overlay.remove();

  document.getElementById("jt-confirm").onclick = () => {
    const statusEl = document.getElementById("jt-status");
    statusEl.textContent = "Saving\u2026";
    statusEl.style.color = "#64748b";

    // Disable buttons to prevent double-submit
    document.getElementById("jt-confirm").disabled = true;
    document.getElementById("jt-dismiss").disabled = true;

    const jobId = extractJobId();
    const payload = {
      company_name: guessCompanyFromPage(),
      role: guessRoleFromPage(),
      job_description: extractJobDescription(),
      source_url: normalizeSourceUrl(window.location.href),
      ...(jobId && { ats_job_id: jobId })
    };

    chrome.runtime.sendMessage({ type: "CAPTURE_APPLICATION", payload }, (response) => {
      if (chrome.runtime.lastError) {
        statusEl.textContent = "Extension error.";
        statusEl.style.color = "#ef4444";
      } else if (response?.error === "token_expired") {
        statusEl.textContent = "Session expired.";
        statusEl.style.color = "#f59e0b";
      } else if (response?.error === "not_authenticated") {
        statusEl.textContent = "Log in first.";
        statusEl.style.color = "#f59e0b";
      } else if (response?.success) {
        statusEl.textContent = "Saved \u2713";
        statusEl.style.color = "#10b981";
      } else {
        statusEl.textContent = `Error: ${response?.error || "unknown"}`;
        statusEl.style.color = "#ef4444";
      }
      // Always remove overlay after brief status flash — prevents DOM persistence
      // across Workday SPA navigation (pushState doesn't reinject content scripts).
      overlayTimeoutId = setTimeout(() => { overlay.remove(); overlayTimeoutId = null; }, 1500);
    });
  };
}

// Clean up overlay on browser back/forward navigation.
window.addEventListener("popstate", removeOverlayAndCancel);

// Listen for HIDE_OVERLAY from background.js (triggered by chrome.tabs.onUpdated
// when Workday SPA navigates to /apply/ via pushState).
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "HIDE_OVERLAY") {
    removeOverlayAndCancel();
  }
  if (message.type === "GET_CAPTURE_DATA") {
    sendResponse(_cachedCaptureData);
  }
});

// Wait for DOM to settle before checking (1.5s covers lazy-rendered ATS pages)
if (document.readyState === "complete" || document.readyState === "interactive") {
  overlayTimeoutId = setTimeout(maybeShowOverlay, 1500);
} else {
  document.addEventListener("DOMContentLoaded", () => {
    overlayTimeoutId = setTimeout(maybeShowOverlay, 1500);
  });
}
