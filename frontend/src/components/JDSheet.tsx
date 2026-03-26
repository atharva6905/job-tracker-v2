"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { fetchAPI } from "@/lib/api";
import type { JobDescription, StructuredJD } from "@/lib/types";

function StructuredJDSection({ data }: { data: StructuredJD }) {
  return (
    <div className="space-y-5">
      {data.summary && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Summary
          </h4>
          <p className="text-sm leading-relaxed">{data.summary}</p>
        </div>
      )}

      {data.responsibilities.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Responsibilities
          </h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.responsibilities.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {data.required_qualifications.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Required Qualifications
          </h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.required_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.preferred_qualifications.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Preferred Qualifications
          </h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.preferred_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.tech_stack.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Tech Stack
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {data.tech_stack.map((t, i) => (
              <span
                key={i}
                className="rounded-full border border-border bg-secondary px-2.5 py-0.5 font-mono text-xs"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.compensation && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Compensation
          </h4>
          <p className="text-sm">{data.compensation}</p>
        </div>
      )}

      {data.location && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Location
          </h4>
          <p className="text-sm">
            {data.location}
            {data.work_model ? ` (${data.work_model})` : ""}
          </p>
        </div>
      )}

      {!data.location && data.work_model && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">
            Work Model
          </h4>
          <p className="text-sm">{data.work_model}</p>
        </div>
      )}

      {data.company_overview && (
        <details className="mt-2">
          <summary className="text-xs font-medium uppercase tracking-editorial text-muted-foreground cursor-pointer">
            Company Overview
          </summary>
          <p className="mt-2 text-sm leading-relaxed">{data.company_overview}</p>
        </details>
      )}
    </div>
  );
}

interface JDSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applicationId: string | null;
  companyName: string;
  role: string;
}

export function JDSheet({
  open,
  onOpenChange,
  applicationId,
  companyName,
  role,
}: JDSheetProps) {
  const [jd, setJd] = useState<JobDescription | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!open || !applicationId) return;
    setLoading(true);
    setError(false);
    setJd(null);

    fetchAPI<JobDescription | null>(
      `/applications/${applicationId}/job-description`
    )
      .then((data) => setJd(data))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [open, applicationId]);

  const structured = jd?.structured_jd ?? null;
  const hasStructuredContent =
    structured &&
    (structured.summary ||
      structured.responsibilities.length > 0 ||
      structured.required_qualifications.length > 0 ||
      structured.tech_stack.length > 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-[580px] bg-card border-border overflow-y-auto"
      >
        <SheetHeader className="pb-4 border-b border-border/50">
          <SheetTitle className="font-display text-2xl font-semibold">
            {jd?.structured_jd?.company_name ?? companyName}
          </SheetTitle>
          <SheetDescription className="text-sm text-muted-foreground">
            {role}
          </SheetDescription>
        </SheetHeader>

        <div className="py-6">
          {loading ? (
            <div className="space-y-3 animate-pulse">
              <div className="h-4 bg-secondary rounded w-3/4" />
              <div className="h-4 bg-secondary rounded w-full" />
              <div className="h-4 bg-secondary rounded w-5/6" />
              <div className="h-4 bg-secondary rounded w-2/3" />
            </div>
          ) : error ? (
            <p className="text-sm text-muted-foreground">
              Could not load job description.
            </p>
          ) : !jd ? (
            <p className="font-display italic text-muted-foreground">
              Job description was not captured for this application.
            </p>
          ) : hasStructuredContent ? (
            <StructuredJDSection data={structured} />
          ) : (
            <div className="max-h-[70vh] overflow-y-auto">
              <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
                {jd.raw_text}
              </pre>
            </div>
          )}
        </div>

        {applicationId && (
          <div className="pt-4 border-t border-border/50">
            <Link
              href={`/applications/${applicationId}`}
              className="font-mono text-xs text-muted-foreground hover:text-accent-gold transition-colors"
              onClick={() => onOpenChange(false)}
            >
              View full details &rarr;
            </Link>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
