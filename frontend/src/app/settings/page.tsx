"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { fetchAPI } from "@/lib/api";
import type { EmailAccount } from "@/lib/types";
import { ArrowLeft, Download, Mail, RefreshCw, Trash2 } from "lucide-react";

export default function SettingsPage() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [disconnectId, setDisconnectId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [resyncingId, setResyncingId] = useState<string | null>(null);
  const resyncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (resyncTimerRef.current) clearTimeout(resyncTimerRef.current);
    };
  }, []);

  useEffect(() => {
    fetchAPI<EmailAccount[]>("/gmail/accounts")
      .then(setAccounts)
      .catch((err) => { console.error("[Settings] failed to load Gmail accounts:", err); })
      .finally(() => setLoading(false));
  }, []);

  const handleConnectGmail = async () => {
    try {
      const data = await fetchAPI<{ authorization_url: string }>("/gmail/connect");
      window.location.href = data.authorization_url;
    } catch (err) {
      console.error("[Settings] gmail connect failed:", err);
    }
  };

  const handleDisconnect = async () => {
    if (!disconnectId) return;
    try {
      await fetchAPI(`/gmail/disconnect/${disconnectId}`, { method: "DELETE" });
      setAccounts((prev) => prev.filter((a) => a.id !== disconnectId));
    } catch (err) {
      console.error("[Settings] disconnect failed:", err);
    } finally {
      setDisconnectId(null);
    }
  };

  const handleResync = async (accountId: string) => {
    setResyncingId(accountId);
    try {
      await fetchAPI(`/gmail/accounts/${accountId}/poll?force=true`, { method: "POST" });
      resyncTimerRef.current = setTimeout(() => setResyncingId(null), 15_000);
    } catch {
      setResyncingId(null);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const supabase = (await import("@/lib/supabase")).createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) throw new Error("Not authenticated");

      const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
      const res = await fetch(`${apiBase}/users/me/export`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "job-tracker-export.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("[Settings] export failed:", err);
    } finally {
      setExporting(false);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      await fetchAPI("/users/me", { method: "DELETE" });
      await signOut();
      router.push("/");
    } catch (err) {
      console.error("[Settings] account deletion failed:", err);
    } finally {
      setDeleting(false);
      setDeleteDialogOpen(false);
    }
  };

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
          <h1 className="font-display text-xl font-semibold">Settings</h1>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8 space-y-8">
        {/* Account info */}
        <section className="border border-border/50 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-3">
            Account
          </h2>
          <p className="text-sm">
            <span className="text-muted-foreground">Email:</span>{" "}
            {user?.email}
          </p>
        </section>

        {/* Gmail accounts */}
        <section className="border border-border/50 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-4">
            Connected Gmail Accounts
          </h2>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground mb-4">
              No Gmail accounts connected. Connect one to enable automatic
              status updates.
            </p>
          ) : (
            <div className="space-y-2 mb-4">
              {accounts.map((account) => (
                <div
                  key={account.id}
                  className="flex items-center justify-between rounded-md border border-border/50 p-3"
                >
                  <div className="flex items-center gap-2">
                    <Mail className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm">{account.email}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={resyncingId === account.id}
                      onClick={() => handleResync(account.id)}
                      title="Re-sync emails from the last 30 days"
                      className="inline-flex items-center gap-1 rounded-md border border-border/50 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                    >
                      <RefreshCw className={`h-3 w-3 ${resyncingId === account.id ? "animate-spin" : ""}`} />
                      {resyncingId === account.id ? "Syncing..." : "Re-sync"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDisconnectId(account.id)}
                      className="inline-flex items-center rounded-md border border-border/50 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Disconnect
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={handleConnectGmail}
            className="inline-flex items-center justify-center w-full rounded-md bg-foreground text-background px-4 py-2.5 text-sm font-medium transition-colors hover:bg-foreground/90"
          >
            <Mail className="mr-2 h-4 w-4" />
            Connect Gmail
          </button>
        </section>

        {/* Data section */}
        <section className="border border-border/50 rounded-lg p-5">
          <h2 className="text-xs font-medium uppercase tracking-editorial text-muted-foreground mb-4">
            Your Data
          </h2>
          <div className="space-y-4">
            <div>
              <button
                type="button"
                onClick={handleExport}
                disabled={exporting}
                className="inline-flex items-center justify-center w-full rounded-md border border-border/50 px-4 py-2.5 text-sm text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
              >
                <Download className="mr-2 h-4 w-4" />
                {exporting ? "Exporting..." : "Download as CSV"}
              </button>
              <p className="mt-1.5 text-xs text-muted-foreground/60">
                Download all your applications as a CSV file
              </p>
            </div>

            <div>
              <button
                type="button"
                onClick={() => setDeleteDialogOpen(true)}
                className="inline-flex items-center justify-center w-full rounded-md bg-destructive/10 border border-destructive/20 text-destructive px-4 py-2.5 text-sm font-medium transition-colors hover:bg-destructive/20"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete my account
              </button>
              <p className="mt-1.5 text-xs text-muted-foreground/60">
                Permanently delete your account and all associated data
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* Disconnect Gmail confirmation */}
      <Dialog
        open={disconnectId !== null}
        onOpenChange={(open) => !open && setDisconnectId(null)}
      >
        <DialogContent onClose={() => setDisconnectId(null)}>
          <DialogHeader>
            <DialogTitle>Disconnect Gmail account?</DialogTitle>
            <DialogDescription>
              This will stop automatic email polling for this account. You can
              reconnect it later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDisconnectId(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDisconnect}>
              Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete account confirmation */}
      <Dialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
      >
        <DialogContent onClose={() => setDeleteDialogOpen(false)}>
          <DialogHeader>
            <DialogTitle>Delete your account?</DialogTitle>
            <DialogDescription>
              This will permanently delete all your data. This cannot be undone.
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
              onClick={handleDeleteAccount}
              disabled={deleting}
            >
              {deleting ? "Deleting..." : "Delete my account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
