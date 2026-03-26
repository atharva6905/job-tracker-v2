"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectItem } from "@/components/ui/select";
import { fetchAPI } from "@/lib/api";
import type { Application, ApplicationStatus, Company, JobDescription, StructuredJD } from "@/lib/types";
import { ArrowLeft, ExternalLink, Trash2 } from "lucide-react";
import { EmailTimeline } from "@/components/EmailTimeline";

const CORRECTABLE_STATUSES: { value: ApplicationStatus; label: string }[] = [
  { value: "APPLIED", label: "Applied" },
  { value: "INTERVIEW", label: "Interview" },
  { value: "OFFER", label: "Offer" },
  { value: "REJECTED", label: "Rejected" },
];

function DeadlineBanner({ deadline, status }: { deadline: string; status: ApplicationStatus }) {
  if (status !== "IN_PROGRESS") return null;
  const deadlineDate = new Date(deadline + "T00:00:00");
  const now = new Date();
  const diffMs = deadlineDate.getTime() - now.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  let colorClass = "border-status-in-progress/30 text-status-in-progress bg-status-in-progress-bg";
  let label = `Application deadline: ${deadlineDate.toLocaleDateString()}`;

  if (diffMs < 0) {
    colorClass = "border-status-rejected/30 text-status-rejected bg-status-rejected-bg";
    label = `Deadline passed: ${deadlineDate.toLocaleDateString()}`;
  } else if (diffDays <= 3) {
    colorClass = "border-status-in-progress/30 text-status-in-progress bg-status-in-progress-bg";
    label = `Deadline in ${Math.ceil(diffDays)} day${Math.ceil(diffDays) === 1 ? "" : "s"}: ${deadlineDate.toLocaleDateString()}`;
  }

  return (
    <div className={`rounded-md border p-3 text-sm font-medium ${colorClass}`}>
      {label}
    </div>
  );
}

function StructuredJDDisplay({ data }: { data: StructuredJD }) {
  return (
    <div className="space-y-5">
      {data.summary && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Summary</h4>
          <p className="text-sm leading-relaxed">{data.summary}</p>
        </div>
      )}

      {data.responsibilities.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Responsibilities</h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.responsibilities.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {data.required_qualifications.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Required Qualifications</h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.required_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.preferred_qualifications.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Preferred Qualifications</h4>
          <ul className="list-disc list-inside text-sm space-y-1 leading-relaxed">
            {data.preferred_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.tech_stack.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Tech Stack</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.tech_stack.map((t, i) => (
              <Badge key={i} variant="secondary" className="font-mono text-xs">{t}</Badge>
            ))}
          </div>
        </div>
      )}

      {data.compensation && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Compensation</h4>
          <p className="text-sm">{data.compensation}</p>
        </div>
      )}

      {data.location && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Location</h4>
          <p className="text-sm">{data.location}{data.work_model ? ` (${data.work_model})` : ""}</p>
        </div>
      )}

      {!data.location && data.work_model && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-2">Work Model</h4>
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

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [application, setApplication] = useState<Application | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [jobDescription, setJobDescription] = useState<JobDescription | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [structuring, setStructuring] = useState(false);
  const [pollingForStructure, setPollingForStructure] = useState(false);
  const structureIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (structureIntervalRef.current) clearInterval(structureIntervalRef.current);
    };
  }, []);

  useEffect(() => {
    if (authLoading || !user) return;

    async function load() {
      try {
        const app = await fetchAPI<Application>(`/applications/${params.id}`);
        setApplication(app);

        const [comp, jd] = await Promise.all([
          fetchAPI<Company>(`/companies/${app.company_id}`),
          fetchAPI<JobDescription | null>(
            `/applications/${params.id}/job-description`
          ).catch(() => null),
        ]);
        setCompany(comp);
        setJobDescription(jd);
      } catch {
        // error handled by fetchAPI (401 signs out)
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [authLoading, user, params.id]);

  // Auto-poll for structured JD on recently created applications
  useEffect(() => {
    if (!application || !jobDescription) return;
    if (jobDescription.structured_jd) return;

    const createdAt = new Date(application.created_at).getTime();
    const fiveMinutesAgo = Date.now() - 5 * 60 * 1000;
    if (createdAt < fiveMinutesAgo) return;

    setPollingForStructure(true);
    let attempts = 0;
    const maxAttempts = 10;

    const interval = setInterval(async () => {
      attempts++;
      try {
        const jd = await fetchAPI<JobDescription | null>(
          `/applications/${params.id}/job-description`
        );
        if (jd?.structured_jd) {
          setJobDescription(jd);
          setPollingForStructure(false);
          clearInterval(interval);
        } else if (attempts >= maxAttempts) {
          setPollingForStructure(false);
          clearInterval(interval);
        }
      } catch {
        setPollingForStructure(false);
        clearInterval(interval);
      }
    }, 3000);

    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [application?.id, jobDescription?.id, jobDescription?.structured_jd]);

  const handleStatusChange = async (newStatus: string) => {
    if (!application || updating) return;
    setUpdating(true);
    try {
      const updated = await fetchAPI<Application>(
        `/applications/${application.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus }),
        }
      );
      setApplication(updated);
    } catch {
      // Could show error toast here
    } finally {
      setUpdating(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await fetchAPI(`/applications/${params.id}`, { method: "DELETE" });
      router.push("/dashboard");
    } catch {
      // Keep dialog open on error so user can retry
    } finally {
      setDeleting(false);
    }
  };

  const handleStructureJD = async () => {
    setStructuring(true);
    try {
      await fetchAPI(`/applications/${params.id}/structure-jd`, {
        method: "POST",
      });
      let attempts = 0;
      const maxAttempts = 10;
      const interval = setInterval(async () => {
        attempts++;
        try {
          const jd = await fetchAPI<JobDescription | null>(
            `/applications/${params.id}/job-description`
          );
          if (jd?.structured_jd) {
            setJobDescription(jd);
            setStructuring(false);
            clearInterval(interval);
            structureIntervalRef.current = null;
          } else if (attempts >= maxAttempts) {
            if (jd) setJobDescription(jd);
            setStructuring(false);
            clearInterval(interval);
            structureIntervalRef.current = null;
          }
        } catch {
          setStructuring(false);
          clearInterval(interval);
          structureIntervalRef.current = null;
        }
      }, 3000);
      structureIntervalRef.current = interval;
    } catch {
      setStructuring(false);
    }
  };

  if (authLoading || !user || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="font-mono text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (!application) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground">Application not found</p>
        <Link href="/dashboard">
          <Button variant="outline">Back to dashboard</Button>
        </Link>
      </div>
    );
  }

  const structured = jobDescription?.structured_jd ?? null;
  const hasStructuredContent = structured && (
    structured.summary ||
    structured.responsibilities.length > 0 ||
    structured.required_qualifications.length > 0 ||
    structured.tech_stack.length > 0
  );

  return (
    <div className="min-h-screen">
      <header className="border-b border-border/50">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-6 py-4">
          <Link
            href="/dashboard"
            className="p-2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="font-display text-xl font-semibold">Application Details</h1>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8 space-y-8">
        {/* Deadline banner */}
        {structured?.application_deadline && application && (
          <DeadlineBanner
            deadline={structured.application_deadline}
            status={application.status}
          />
        )}

        {/* Header info */}
        <section className="border border-border/50 rounded-lg p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="font-display text-2xl font-semibold">
                {company?.name ?? "Unknown Company"}
              </h2>
              <p className="mt-1 text-muted-foreground">
                {application.role}
              </p>
            </div>
            <StatusBadge status={application.status} />
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            {application.date_applied && (
              <div>
                <p className="text-xs uppercase tracking-editorial text-muted-foreground mb-1">
                  Date Applied
                </p>
                <p>{new Date(application.date_applied + "T00:00:00").toLocaleDateString()}</p>
              </div>
            )}
            <div>
              <p className="text-xs uppercase tracking-editorial text-muted-foreground mb-1">Created</p>
              <p>{new Date(application.created_at).toLocaleDateString()}</p>
            </div>
            {application.source_url && (
              <div className="col-span-2">
                <p className="text-xs uppercase tracking-editorial text-muted-foreground mb-1">
                  Job Posting
                </p>
                <a
                  href={application.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-accent-gold hover:underline text-sm"
                >
                  View original posting
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            )}
          </div>

          {application.notes && (
            <div className="mt-4 pt-4 border-t border-border/50">
              <p className="text-xs uppercase tracking-editorial text-muted-foreground mb-1">
                Notes
              </p>
              <p className="text-sm whitespace-pre-wrap">
                {application.notes}
              </p>
            </div>
          )}
        </section>

        {/* Correct status */}
        <section className="border border-border/50 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-3">
            Correct Status
          </h2>
          <p className="mb-3 text-sm text-muted-foreground">
            If the automated status is wrong, you can correct it here.
          </p>
          <Select
            value={application.status === "IN_PROGRESS" ? "" : application.status}
            onValueChange={handleStatusChange}
            disabled={updating}
          >
            <SelectItem value="" disabled>
              Select status...
            </SelectItem>
            {CORRECTABLE_STATUSES.map(({ value, label }) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </Select>
        </section>

        {/* Job Description */}
        <section className="border border-border/50 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-4">
            Job Description
          </h2>
          {jobDescription ? (
            <>
              <p className="mb-3 font-mono text-xs text-muted-foreground/60">
                Captured at apply time ({new Date(jobDescription.captured_at).toLocaleString()})
              </p>
              {hasStructuredContent ? (
                <StructuredJDDisplay data={structured} />
              ) : pollingForStructure || structuring ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-4 bg-secondary rounded w-3/4" />
                  <div className="h-4 bg-secondary rounded w-full" />
                  <div className="h-4 bg-secondary rounded w-5/6" />
                  <div className="h-4 bg-secondary rounded w-2/3" />
                  <div className="h-4 bg-secondary rounded w-4/5" />
                  <p className="font-mono text-xs text-muted-foreground mt-2 animate-none">
                    Structuring job description...
                  </p>
                </div>
              ) : (
                <>
                  <div className="max-h-96 overflow-y-auto rounded-md border border-border/50 bg-secondary/50 p-4">
                    <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
                      {jobDescription.raw_text}
                    </pre>
                  </div>
                  <button
                    type="button"
                    className="mt-3 rounded-md border border-border/50 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    onClick={handleStructureJD}
                    disabled={structuring}
                  >
                    Structure JD
                  </button>
                </>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              Job description not captured — the extension was not active when
              this application was detected.
            </p>
          )}
        </section>

        <EmailTimeline applicationId={params.id} />

        {/* Danger zone */}
        <section className="border border-destructive/20 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-destructive mb-3">
            Danger Zone
          </h2>
          <button
            type="button"
            onClick={() => setDeleteDialogOpen(true)}
            className="inline-flex items-center rounded-md bg-destructive/10 border border-destructive/20 text-destructive px-4 py-2 text-sm font-medium transition-colors hover:bg-destructive/20"
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete application
          </button>
        </section>
      </main>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
      >
        <DialogContent onClose={() => setDeleteDialogOpen(false)}>
          <DialogHeader>
            <DialogTitle>Delete this application?</DialogTitle>
            <DialogDescription>
              This cannot be undone. You can re-track it by visiting the job
              posting again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
