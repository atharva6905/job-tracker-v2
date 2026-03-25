"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  const deadlineDate = new Date(deadline);
  const now = new Date();
  const diffMs = deadlineDate.getTime() - now.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  let bgClass = "bg-yellow-50 border-yellow-200 text-yellow-800";
  let label = `Application deadline: ${deadlineDate.toLocaleDateString()}`;

  if (diffMs < 0) {
    bgClass = "bg-red-50 border-red-200 text-red-800";
    label = `Deadline passed: ${deadlineDate.toLocaleDateString()}`;
  } else if (diffDays <= 3) {
    bgClass = "bg-amber-50 border-amber-200 text-amber-800";
    label = `Deadline in ${Math.ceil(diffDays)} day${Math.ceil(diffDays) === 1 ? "" : "s"}: ${deadlineDate.toLocaleDateString()}`;
  }

  return (
    <div className={`rounded-md border p-3 text-sm font-medium ${bgClass}`}>
      {label}
    </div>
  );
}

function StructuredJDDisplay({ data }: { data: StructuredJD }) {
  return (
    <div className="space-y-4">
      {data.summary && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Summary</h4>
          <p className="text-sm">{data.summary}</p>
        </div>
      )}

      {data.responsibilities.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Responsibilities</h4>
          <ul className="list-disc list-inside text-sm space-y-1">
            {data.responsibilities.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {data.required_qualifications.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Required Qualifications</h4>
          <ul className="list-disc list-inside text-sm space-y-1">
            {data.required_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.preferred_qualifications.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Preferred Qualifications</h4>
          <ul className="list-disc list-inside text-sm space-y-1">
            {data.preferred_qualifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {data.tech_stack.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Tech Stack</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.tech_stack.map((t, i) => (
              <Badge key={i} variant="secondary">{t}</Badge>
            ))}
          </div>
        </div>
      )}

      {data.compensation && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Compensation</h4>
          <p className="text-sm">{data.compensation}</p>
        </div>
      )}

      {data.location && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Location</h4>
          <p className="text-sm">{data.location}{data.work_model ? ` (${data.work_model})` : ""}</p>
        </div>
      )}

      {!data.location && data.work_model && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">Work Model</h4>
          <p className="text-sm">{data.work_model}</p>
        </div>
      )}

      {data.company_overview && (
        <details className="mt-2">
          <summary className="text-sm font-medium text-muted-foreground cursor-pointer">
            Company Overview
          </summary>
          <p className="mt-1 text-sm">{data.company_overview}</p>
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
      // Poll for the result after a short delay (background task)
      setTimeout(async () => {
        try {
          const jd = await fetchAPI<JobDescription | null>(
            `/applications/${params.id}/job-description`
          );
          if (jd) setJobDescription(jd);
        } catch {
          // ignore
        } finally {
          setStructuring(false);
        }
      }, 5000);
    } catch {
      setStructuring(false);
    }
  };

  if (authLoading || !user || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
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
  // Guard against all-empty structured data (e.g. from structuring empty raw_text)
  const hasStructuredContent = structured && (
    structured.summary ||
    structured.responsibilities.length > 0 ||
    structured.required_qualifications.length > 0 ||
    structured.tech_stack.length > 0
  );

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-4 py-3">
          <Link href="/dashboard">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <h1 className="text-xl font-semibold">Application Details</h1>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        {/* Deadline banner */}
        {structured?.application_deadline && application && (
          <DeadlineBanner
            deadline={structured.application_deadline}
            status={application.status}
          />
        )}

        {/* Header info */}
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between">
              <div>
                <CardTitle className="text-2xl">
                  {company?.name ?? "Unknown Company"}
                </CardTitle>
                <p className="mt-1 text-lg text-muted-foreground">
                  {application.role}
                </p>
              </div>
              <StatusBadge status={application.status} />
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              {application.date_applied && (
                <div>
                  <p className="font-medium text-muted-foreground">
                    Date Applied
                  </p>
                  <p>{new Date(application.date_applied).toLocaleDateString()}</p>
                </div>
              )}
              <div>
                <p className="font-medium text-muted-foreground">Created</p>
                <p>{new Date(application.created_at).toLocaleDateString()}</p>
              </div>
              {application.source_url && (
                <div className="col-span-2">
                  <p className="font-medium text-muted-foreground">
                    Job Posting
                  </p>
                  <a
                    href={application.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                  >
                    View original posting
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}
            </div>

            {application.notes && (
              <div>
                <p className="text-sm font-medium text-muted-foreground">
                  Notes
                </p>
                <p className="mt-1 text-sm whitespace-pre-wrap">
                  {application.notes}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Correct status */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Correct Status</CardTitle>
          </CardHeader>
          <CardContent>
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
          </CardContent>
        </Card>

        {/* Job Description */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Job Description</CardTitle>
          </CardHeader>
          <CardContent>
            {jobDescription ? (
              <>
                <p className="mb-2 text-xs text-muted-foreground">
                  Captured at apply time ({new Date(jobDescription.captured_at).toLocaleString()})
                </p>
                {hasStructuredContent ? (
                  <StructuredJDDisplay data={structured} />
                ) : (
                  <>
                    <div className="max-h-96 overflow-y-auto rounded-md border bg-muted/50 p-4">
                      <pre className="whitespace-pre-wrap text-sm font-mono">
                        {jobDescription.raw_text}
                      </pre>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-3"
                      onClick={handleStructureJD}
                      disabled={structuring}
                    >
                      {structuring ? "Structuring..." : "Structure JD"}
                    </Button>
                  </>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Job description not captured — the extension was not active when
                this application was detected.
              </p>
            )}
          </CardContent>
        </Card>

        <EmailTimeline applicationId={params.id} />

        {/* Danger zone */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Danger Zone</CardTitle>
          </CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={() => setDeleteDialogOpen(true)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete application
            </Button>
          </CardContent>
        </Card>
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
