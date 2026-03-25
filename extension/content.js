// ─── WORKDAY-ONLY GUARD ───────────────────────────────────────────────────────
// Content script only runs on Workday pages. manifest.json already restricts
// injection to *.myworkdayjobs.com, *.myworkday.com, *.myworkdaysite.com — this
// guard is defense-in-depth. Hostname check covers all Workday subdomain formats
// (bmo.wd3.myworkdayjobs.com, company.myworkday.com, etc.).
function isWorkdayPage() {
  const meta = document.querySelector('meta[name="application-name"]');
  if (meta?.content?.toLowerCase() === "workday") return true;
  return /\.(myworkdayjobs|myworkday|myworkdaysite)\.com$/i.test(window.location.hostname);
}

const pathname = window.location.pathname;
const isJobPage = /\/job\/[^/]/.test(pathname) || /\/details\/[^/]/.test(pathname);
if (!isWorkdayPage() || /\/apply(\/|$)/.test(pathname) || !isJobPage) {
  // Not a Workday job detail page (requires /job/{id} or /details/{id}), or on an apply form — exit.
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
// Supports both /job/{location}/{id} and /details/{id} patterns.
// e.g. /en-US/sdm_careers/job/.../Cashier_R2000648316 → "Cashier_R2000648316"
// e.g. /en-US/External/details/Software-Developer_R260004443-1 → "Software-Developer_R260004443-1"
function extractJobId() {
  const p = window.location.pathname;
  // Try /details/{id} first (single segment after /details/)
  const detailsMatch = p.match(/\/details\/([^/?#]+)/);
  if (detailsMatch) return detailsMatch[1];
  // Fall back to /job/{...}/{id} (last segment after /job/)
  const jobMatch = p.match(/\/job\/([^/?#]+)/);
  return jobMatch ? jobMatch[1] : null;
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
  const pathMatch = window.location.pathname.match(/^\/[^/]+\/([^/]+)\/(?:job|details)\//);
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

// Defer JD extraction until dynamic content has loaded (same delay as overlay).
// Once extracted, persist to chrome.storage.session so background.js can read it
// even if this content script becomes unreachable after SPA navigation to /apply/.
setTimeout(() => {
  _cachedCaptureData.job_description = extractJobDescription();
  const jobId = extractJobId();
  if (jobId) {
    chrome.storage.session.set({ [`job_${jobId}`]: { ..._cachedCaptureData } });
  }
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
    "z-index:2147483647",
    "background:#ffffff",
    "border:1px solid #e2e8f0",
    "border-radius:12px",
    "padding:12px 16px",
    "box-shadow:0 8px 24px rgba(0,0,0,0.12)",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    "max-width:260px"
  ].join(";");

  // Passive indicator — no buttons, no user interaction required.
  // Auto-capture fires when the user navigates to /apply/.
  overlay.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;">
      <span style="font-size:14px;">&#9989;</span>
      <p style="margin:0;font-weight:500;font-size:13px;color:#0f172a;">Job Tracker active</p>
    </div>
    <p style="margin:4px 0 0;font-size:11px;color:#64748b;line-height:1.4;">
      Will auto-track when you apply.
    </p>
  `;

  document.body.appendChild(overlay);

  // Auto-dismiss after 3 seconds
  overlayTimeoutId = setTimeout(() => { overlay.remove(); overlayTimeoutId = null; }, 3000);
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
