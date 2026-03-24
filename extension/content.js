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

if (!isWorkdayPage() || /\/apply(\/|$)/.test(window.location.pathname)) {
  // Not a Workday job posting page, or on an apply form page — exit immediately.
  // No marker, no overlay, no scraping.
  throw new Error("job-tracker-v2: not a Workday job posting page, exiting content script");
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
  const parts = window.location.pathname.split("/job/")[1]?.split("/") || [];
  return parts[parts.length - 1] || null;
}

// ─── JD EXTRACTION ────────────────────────────────────────────────────────────
function extractJobDescription() {
  // SECURITY: ONLY read from structural/display elements — NEVER from form fields.
  // Application forms can contain passwords, SSNs, EEO data, salary info.
  // We must not capture any of that.
  const ALLOWED = "h1, h2, h3, p, li, section, article";
  const FORBIDDEN = "input, textarea, select";

  const forbiddenSet = new Set(document.querySelectorAll(FORBIDDEN));

  return [...document.querySelectorAll(ALLOWED)]
    .filter(el => {
      // Exclude if the element itself is forbidden
      if (forbiddenSet.has(el)) return false;
      // Exclude if any ancestor is a form field container
      if (el.closest(FORBIDDEN)) return false;
      return true;
    })
    .map(el => el.textContent.trim())
    .filter(t => t.length > 20)
    .join("\n")
    .substring(0, 50000); // Hard cap — matches backend ExtensionCaptureRequest.job_description max_length
}

function guessRoleFromPage() {
  const h1 = document.querySelector("h1")?.textContent?.trim() || "";
  const title = document.title || "";
  // Prefer h1 (usually the job title on ATS pages); fall back to page title
  return (h1 || title).substring(0, 255);
}

function guessCompanyFromPage() {
  // Best-effort: split page title on common separators
  // e.g. "Software Engineer - Google Careers" → "Google Careers"
  const parts = document.title.split(/[-–|]/);
  return (parts[parts.length - 1]?.trim() || "Unknown").substring(0, 255);
}

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

    const payload = {
      company_name: guessCompanyFromPage(),
      role: guessRoleFromPage(),
      job_description: extractJobDescription(),
      source_url: window.location.href
    };

    chrome.runtime.sendMessage({ type: "CAPTURE_APPLICATION", payload }, (response) => {
      if (chrome.runtime.lastError) {
        statusEl.textContent = "Extension error. Try reloading.";
        statusEl.style.color = "#ef4444";
        return;
      }

      if (response?.error === "token_expired") {
        statusEl.textContent = "Session expired \u2014 please log in via the web app.";
        statusEl.style.color = "#f59e0b";
      } else if (response?.error === "not_authenticated") {
        statusEl.textContent = "Log in to job-tracker-v2 first.";
        statusEl.style.color = "#f59e0b";
      } else if (response?.success) {
        statusEl.textContent = "Saved \u2713";
        statusEl.style.color = "#10b981";
        setTimeout(() => overlay.remove(), 2000);
      } else {
        statusEl.textContent = `Error: ${response?.error || "unknown"}. Try again.`;
        statusEl.style.color = "#ef4444";
        document.getElementById("jt-confirm").disabled = false;
        document.getElementById("jt-dismiss").disabled = false;
      }
    });
  };
}

// Wait for DOM to settle before checking (1.5s covers lazy-rendered ATS pages)
if (document.readyState === "complete" || document.readyState === "interactive") {
  setTimeout(maybeShowOverlay, 1500);
} else {
  document.addEventListener("DOMContentLoaded", () => setTimeout(maybeShowOverlay, 1500));
}
