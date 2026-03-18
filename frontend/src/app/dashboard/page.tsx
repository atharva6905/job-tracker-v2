"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { SetupChecklist } from "@/components/setup-checklist";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { fetchAPI } from "@/lib/api";
import type { Application, ApplicationStatus, Company } from "@/lib/types";
import { LogOut, Settings } from "lucide-react";

const COLUMNS: { status: ApplicationStatus; label: string }[] = [
  { status: "IN_PROGRESS", label: "In Progress" },
  { status: "APPLIED", label: "Applied" },
  { status: "INTERVIEW", label: "Interview" },
  { status: "OFFER", label: "Offer" },
  { status: "REJECTED", label: "Rejected" },
];

export default function DashboardPage() {
  const { user, loading: authLoading, signOut } = useAuth();
  const [applications, setApplications] = useState<Application[]>([]);
  const [companies, setCompanies] = useState<Record<string, Company>>({});
  const [dataLoading, setDataLoading] = useState(true);

  // Only fetch data after auth is confirmed
  useEffect(() => {
    if (authLoading || !user) return;

    async function load() {
      try {
        const [apps, comps] = await Promise.all([
          fetchAPI<Application[]>("/applications?limit=100"),
          fetchAPI<Company[]>("/companies"),
        ]);
        setApplications(apps);
        const compMap: Record<string, Company> = {};
        for (const c of comps) {
          compMap[c.id] = c;
        }
        setCompanies(compMap);
      } catch {
        // error handled by fetchAPI (401 signs out)
      } finally {
        setDataLoading(false);
      }
    }
    load();
  }, [authLoading, user]);

  // Show spinner while auth is initializing or while redirect is pending
  if (authLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const appsByStatus = (status: ApplicationStatus) =>
    applications.filter((a) => a.status === status);

  const formatDate = (app: Application) => {
    const dateStr = app.status === "IN_PROGRESS" ? app.created_at : app.date_applied;
    if (!dateStr) return null;
    return new Date(dateStr).toLocaleDateString();
  };

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <h1 className="text-xl font-semibold">Job Tracker</h1>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">{user.email}</span>
            <Link href="/settings">
              <Button variant="ghost" size="icon">
                <Settings className="h-4 w-4" />
              </Button>
            </Link>
            <Button variant="ghost" size="icon" onClick={signOut}>
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <SetupChecklist />

        {dataLoading ? (
          <div className="flex justify-center py-12">
            <p className="text-muted-foreground">Loading applications...</p>
          </div>
        ) : applications.length === 0 ? (
          <div className="flex justify-center py-12">
            <p className="text-muted-foreground">
              No applications yet. Install the extension and start applying!
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
            {COLUMNS.map(({ status, label }) => (
              <div key={status}>
                <div className="mb-3 flex items-center gap-2">
                  <h2 className="text-sm font-semibold">{label}</h2>
                  <span className="text-xs text-muted-foreground">
                    {appsByStatus(status).length}
                  </span>
                </div>
                <div className="space-y-2">
                  {appsByStatus(status).map((app) => (
                    <Link key={app.id} href={`/applications/${app.id}`}>
                      <Card className="cursor-pointer transition-shadow hover:shadow-md">
                        <CardContent className="p-3">
                          <p className="text-sm font-medium truncate">
                            {companies[app.company_id]?.name ?? "Unknown"}
                          </p>
                          <p className="text-xs text-muted-foreground truncate">
                            {app.role}
                          </p>
                          <div className="mt-2 flex items-center justify-between">
                            <StatusBadge status={app.status} />
                            {formatDate(app) && (
                              <span className="text-xs text-muted-foreground">
                                {formatDate(app)}
                              </span>
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
