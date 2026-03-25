import type { ApplicationStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<ApplicationStatus, string> = {
  IN_PROGRESS: "bg-status-in-progress-bg text-status-in-progress border-status-in-progress/20",
  APPLIED: "bg-status-applied-bg text-status-applied border-status-applied/20",
  INTERVIEW: "bg-status-interview-bg text-status-interview border-status-interview/20",
  OFFER: "bg-status-offer-bg text-status-offer border-status-offer/20",
  REJECTED: "bg-status-rejected-bg text-status-rejected border-status-rejected/20",
};

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  IN_PROGRESS: "In Progress",
  APPLIED: "Applied",
  INTERVIEW: "Interview",
  OFFER: "Offer",
  REJECTED: "Rejected",
};

export function StatusBadge({ status }: { status: ApplicationStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-editorial",
        STATUS_STYLES[status]
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
