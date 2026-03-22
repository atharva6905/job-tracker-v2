# TODOS

## Open Items

### Cleanup job for orphaned PARSE_ERROR emails
**What:** Add a periodic cleanup pass that deletes `raw_emails` rows where
`gemini_signal = 'PARSE_ERROR'` AND `linked_application_id IS NULL` AND
`received_at < NOW() - INTERVAL '30 days'`.

**Why:** PARSE_ERROR emails that never resolve (Gemini consistently fails on them,
or the app they might have matched was deleted) accumulate in `raw_emails` indefinitely
with no linked application. The IN_PROGRESS-gated poll (chunk 18) increases the volume
of stored PARSE_ERRORs because emails for users with active apps are now always stored
on Gemini failure, regardless of whether the company ever matches.

**Pros:** Prevents unbounded table growth; keeps user data export clean; reduces noise
in the raw_emails timeline view.

**Cons:** Requires a new scheduled job or an end-of-poll cleanup pass. Low complexity
(single DELETE query), but needs a test.

**Context:** PARSE_ERROR emails are stored in `raw_emails` when Gemini fails AND the
user has at least one active application (coarse gate passed). The retry loop re-classifies
them on the next poll. If they never resolve (e.g. the email is truly malformed, or
Gemini consistently times out on this email), they stay in `raw_emails` forever.
The cleanup should run as an end-of-poll step in `poll_gmail_account` or as a separate
APScheduler job. A 30-day TTL matches the initial lookback window used at poll start.

**Depends on:** IN_PROGRESS-gated poll feature (chunk 18) — the gating change is what
creates the increased PARSE_ERROR storage volume that motivates this item.
