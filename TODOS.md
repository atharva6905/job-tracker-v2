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

---

### Atomicity gap: PARSE_ERROR retry loop commits signal before transition
**What:** In `poll_gmail_account`'s retry loop, `raw_email.gemini_signal` is updated
and committed *before* `process_email_signal` is called. If `process_email_signal`
raises after that commit, the email has a non-PARSE_ERROR signal (e.g. `APPLIED`) but
`linked_application_id` is still `NULL`. The retry query (`gemini_signal = 'PARSE_ERROR'`)
will never pick it up again — the email is permanently stranded with no linked application.

**Why:** The same commit-before-transition pattern exists in the main loop (raw_email
committed before `process_email_signal`). In the main loop this is acceptable because the
email has the correct Gemini signal stored. In the retry loop it's worse: the email
transitions out of the retry-eligible state (`PARSE_ERROR → APPLIED`) before the
downstream work completes.

**Pros:** Fixing this closes a silent data corruption path where DB errors or crashes
mid-retry leave orphaned raw_emails that look processed but are not.

**Cons:** Requires either (a) deferring the signal commit until after `process_email_signal`
succeeds, or (b) storing the new signal in a separate staging field and only promoting it
on success. Moderate complexity.

**Context:** Surfaced by adversarial review of chunk 18. The failure requires a DB error
or process crash between the `db.commit()` on line ~287 and the `process_email_signal`
call on line ~305 in `poll_job.py`. Low probability in practice but produces silent state
corruption when it occurs.

**Depends on:** None — independent of the cleanup job above.
