import { Badge } from "@/components/ui/badge";
import type { ApplicationStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<ApplicationStatus, string> = {
  IN_PROGRESS: "bg-blue-100 text-blue-800 border-blue-200",
  APPLIED: "bg-yellow-100 text-yellow-800 border-yellow-200",
  INTERVIEW: "bg-purple-100 text-purple-800 border-purple-200",
  OFFER: "bg-green-100 text-green-800 border-green-200",
  REJECTED: "bg-red-100 text-red-800 border-red-200",
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
    <Badge variant="outline" className={cn(STATUS_STYLES[status])}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}
