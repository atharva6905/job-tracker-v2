"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth-provider";
import { SetupChecklist } from "@/components/setup-checklist";
import { StatusBadge } from "@/components/status-badge";
import { JDSheet } from "@/components/JDSheet";
import { fetchAPI } from "@/lib/api";
import type { Application, ApplicationStatus, Company } from "@/lib/types";
import { ArrowRight, FileText, LogOut, Settings } from "lucide-react";

const STATUS_FILTERS: { value: ApplicationStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "IN_PROGRESS", label: "In Progress" },
  { value: "APPLIED", label: "Applied" },
  { value: "INTERVIEW", label: "Interview" },
  { value: "OFFER", label: "Offer" },
  { value: "REJECTED", label: "Rejected" },
];

export default function DashboardPage() {
  const { user, loading: authLoading, signOut } = useAuth();
  const [applications, setApplications] = useState<Application[]>([]);
  const [companies, setCompanies] = useState<Record<string, Company>>({});
  const [dataLoading, setDataLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "ALL">("ALL");
  const [jdSheet, setJdSheet] = useState<{
    open: boolean;
    appId: string | null;
    company: string;
    role: string;
  }>({ open: false, appId: null, company: "", role: "" });

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
      } catch (err) {
        console.error("[Dashboard] data load failed:", err);
        setError("Failed to load applications. Check browser console for details.");
      } finally {
        setDataLoading(false);
      }
    }
    load();
  }, [authLoading, user]);

  const filtered = useMemo(() => {
    let result = applications;
    if (statusFilter !== "ALL") {
      result = result.filter((a) => a.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((a) => {
        const companyName = (a.display_company_name ?? companies[a.company_id]?.name ?? "").toLowerCase();
        return companyName.includes(q) || a.role.toLowerCase().includes(q);
      });
    }
    return [...result].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [applications, statusFilter, search, companies]);

  const formatDate = (app: Application) => {
    const dateStr = app.date_applied || app.created_at;
    if (!dateStr) return null;
    const d = dateStr.length === 10 ? new Date(dateStr + "T00:00:00") : new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  if (authLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground font-mono text-sm">Loading...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-border/50">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <h1 className="font-display text-xl font-semibold tracking-tight">
            Job Tracker
          </h1>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-muted-foreground">
              {user.email}
            </span>
            <Link
              href="/settings"
              className="p-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <Settings className="h-4 w-4" />
            </Link>
            <button
              type="button"
              onClick={signOut}
              className="p-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <SetupChecklist />

        {/* Page heading */}
        <div className="mb-8">
          <h2 className="font-display text-4xl font-semibold tracking-tight">
            Applications
          </h2>
          <div className="mt-2 h-px bg-gradient-to-r from-accent-gold/40 to-transparent" />
        </div>

        {/* Search + filters */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <input
              type="text"
              placeholder="Search company or role..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-transparent border-b border-border/50 pb-1 text-sm font-sans text-foreground placeholder:text-muted-foreground/60 focus:border-accent-gold focus:outline-none transition-colors w-64"
            />
          </div>

          <div className="flex items-center gap-1">
            {STATUS_FILTERS.map(({ value, label }) => (
              <button
                type="button"
                key={value}
                onClick={() => setStatusFilter(value)}
                className={`px-3 py-1.5 text-[11px] font-medium uppercase tracking-editorial transition-colors ${
                  statusFilter === value
                    ? "text-accent-gold border-b-2 border-accent-gold"
                    : "text-muted-foreground hover:text-foreground border-b-2 border-transparent"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Row count — hidden during loading to avoid showing "0 applications" before data arrives */}
        {!dataLoading && applications.length > 0 && (
          <div className="mb-3">
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {filtered.length} application{filtered.length !== 1 ? "s" : ""}
            </span>
          </div>
        )}

        {error && (
          <div className="mb-6 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        {dataLoading ? (
          <div className="py-16 text-center">
            <p className="font-mono text-sm text-muted-foreground">
              Loading applications...
            </p>
          </div>
        ) : applications.length === 0 && !error ? (
          <div className="py-24 text-center">
            <h3 className="font-display text-2xl font-semibold text-foreground/80">
              No applications yet
            </h3>
            <p className="mt-3 text-sm text-muted-foreground max-w-sm mx-auto">
              Install the Chrome extension and start applying on Workday.
              Applications are captured automatically.
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-sm text-muted-foreground">
              No applications match your filters.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="pb-3 text-left text-[11px] font-medium uppercase tracking-editorial text-muted-foreground">
                    Company
                  </th>
                  <th className="pb-3 text-left text-[11px] font-medium uppercase tracking-editorial text-muted-foreground">
                    Role
                  </th>
                  <th className="pb-3 text-left text-[11px] font-medium uppercase tracking-editorial text-muted-foreground">
                    Status
                  </th>
                  <th className="pb-3 text-left text-[11px] font-medium uppercase tracking-editorial text-muted-foreground font-mono">
                    Date
                  </th>
                  <th className="pb-3 text-center text-[11px] font-medium uppercase tracking-editorial text-muted-foreground">
                    JD
                  </th>
                  <th className="pb-3 w-10" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((app) => {
                  const companyName =
                    app.display_company_name ?? companies[app.company_id]?.name ?? "Unknown";
                  return (
                    <tr
                      key={app.id}
                      className="group border-l-2 border-transparent border-b border-white/[0.06] transition-all hover:border-l-accent-gold hover:bg-white/[0.015]"
                    >
                      <td className="py-3.5 pr-4">
                        <span className="text-sm font-medium">
                          {companyName}
                        </span>
                      </td>
                      <td className="py-3.5 pr-4">
                        <span className="text-sm text-muted-foreground">
                          {app.role}
                        </span>
                      </td>
                      <td className="py-3.5 pr-4">
                        <StatusBadge status={app.status} />
                      </td>
                      <td className="py-3.5 pr-4">
                        <span className="font-mono text-xs text-muted-foreground tabular-nums">
                          {formatDate(app) ?? "\u2014"}
                        </span>
                      </td>
                      <td className="py-3.5 text-center">
                        <button
                          type="button"
                          onClick={() =>
                            setJdSheet({
                              open: true,
                              appId: app.id,
                              company: companyName,
                              role: app.role,
                            })
                          }
                          className="inline-flex items-center justify-center p-1.5 rounded transition-colors text-muted-foreground/50 hover:text-accent-gold"
                          title="View job description"
                        >
                          <FileText className="h-4 w-4" />
                        </button>
                      </td>
                      <td className="py-3.5 text-right">
                        <Link
                          href={`/applications/${app.id}`}
                          className="inline-flex items-center p-1.5 text-muted-foreground/40 hover:text-accent-gold transition-colors"
                        >
                          <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>

      <JDSheet
        open={jdSheet.open}
        onOpenChange={(open) => setJdSheet((prev) => ({ ...prev, open }))}
        applicationId={jdSheet.appId}
        companyName={jdSheet.company}
        role={jdSheet.role}
      />
    </div>
  );
}
