"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAPI } from "@/lib/api";
import type { RawEmail } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIGNAL_STYLES: Record<string, string> = {
  APPLIED: "bg-status-applied-bg text-status-applied",
  INTERVIEW: "bg-status-interview-bg text-status-interview",
  OFFER: "bg-status-offer-bg text-status-offer",
  REJECTED: "bg-status-rejected-bg text-status-rejected",
  IRRELEVANT: "bg-secondary text-muted-foreground",
  BELOW_THRESHOLD: "bg-status-in-progress-bg text-status-in-progress",
  PARSE_ERROR: "bg-secondary text-muted-foreground",
};

function SignalBadge({ signal }: { signal: string | null }) {
  const style =
    (signal && SIGNAL_STYLES[signal]) || "bg-secondary text-muted-foreground";
  return (
    <span
      className={cn("rounded-full px-2 py-0.5 text-xs font-medium", style)}
    >
      {signal ?? "unknown"}
    </span>
  );
}

function EmailEntry({ email }: { email: RawEmail }) {
  const [expanded, setExpanded] = useState(false);

  let formattedDate = "Unknown date";
  if (email.received_at) {
    const d = new Date(email.received_at);
    const datePart = d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    const timePart = d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
    formattedDate = `${datePart} at ${timePart}`;
  }

  const truncatedSender =
    email.sender && email.sender.length > 40
      ? email.sender.slice(0, 40) + "\u2026"
      : email.sender;

  return (
    <div className="relative pl-6">
      <div className="absolute left-[-4.5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-border bg-background" />
      <div className="space-y-1 pb-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{formattedDate}</span>
          <SignalBadge signal={email.gemini_signal} />
          {email.gemini_confidence != null && (
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {Math.round(email.gemini_confidence * 100)}%
            </span>
          )}
        </div>
        {truncatedSender && (
          <p className="text-xs text-muted-foreground">{truncatedSender}</p>
        )}
        {email.body_snippet && (
          <div>
            {expanded && (
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                {email.body_snippet}
              </p>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1 text-xs text-accent-gold hover:underline"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function EmailTimeline({ applicationId }: { applicationId: string }) {
  const [emails, setEmails] = useState<RawEmail[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetchAPI<RawEmail[]>(`/applications/${applicationId}/emails`)
      .then(setEmails)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [applicationId]);

  return (
    <section className="border border-border/50 rounded-lg p-5">
      <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-4">
        Email History
      </h2>
      {loading ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-64" />
              <Skeleton className="h-3 w-full" />
            </div>
          ))}
        </div>
      ) : error ? (
        <p className="text-sm text-muted-foreground">
          Could not load email history.
        </p>
      ) : emails && emails.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No emails linked to this application yet.
        </p>
      ) : (
        <div className="border-l border-border">
          {emails!.map((email) => (
            <EmailEntry key={email.id} email={email} />
          ))}
        </div>
      )}
    </section>
  );
}
