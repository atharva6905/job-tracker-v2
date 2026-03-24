"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
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
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleConnectGmail = async () => {
    try {
      const data = await fetchAPI<{ authorization_url: string }>("/gmail/connect");
      window.location.href = data.authorization_url;
    } catch {
      // Error handled by fetchAPI
    }
  };

  const handleDisconnect = async () => {
    if (!disconnectId) return;
    try {
      await fetchAPI(`/gmail/disconnect/${disconnectId}`, { method: "DELETE" });
      setAccounts((prev) => prev.filter((a) => a.id !== disconnectId));
    } catch {
      // Error handled by fetchAPI
    } finally {
      setDisconnectId(null);
    }
  };

  const handleResync = async (accountId: string) => {
    setResyncingId(accountId);
    try {
      await fetchAPI(`/gmail/accounts/${accountId}/poll?force=true`, { method: "POST" });
      // Poll runs in the background — keep button disabled so it doesn't look like a no-op
      resyncTimerRef.current = setTimeout(() => setResyncingId(null), 15_000);
    } catch {
      // Error handled by fetchAPI — reset immediately on failure
      setResyncingId(null);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const data = await fetchAPI<Record<string, unknown>>("/users/me/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "job-tracker-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Error handled by fetchAPI
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
    } catch {
      // Error handled by fetchAPI
    } finally {
      setDeleting(false);
      setDeleteDialogOpen(false);
    }
  };

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-4 py-3">
          <Link href="/dashboard">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <h1 className="text-xl font-semibold">Settings</h1>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        {/* Account info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Account</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm">
              <span className="text-muted-foreground">Email:</span>{" "}
              {user?.email}
            </p>
          </CardContent>
        </Card>

        {/* Gmail accounts */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Connected Gmail Accounts</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : accounts.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No Gmail accounts connected. Connect one to enable automatic
                status updates.
              </p>
            ) : (
              <div className="space-y-2">
                {accounts.map((account) => (
                  <div
                    key={account.id}
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Mail className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm">{account.email}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={resyncingId === account.id}
                        onClick={() => handleResync(account.id)}
                        title="Re-sync emails from the last 30 days"
                      >
                        <RefreshCw className={`h-3 w-3 mr-1 ${resyncingId === account.id ? "animate-spin" : ""}`} />
                        {resyncingId === account.id ? "Syncing…" : "Re-sync"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setDisconnectId(account.id)}
                      >
                        Disconnect
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <Button onClick={handleConnectGmail} className="w-full">
              <Mail className="mr-2 h-4 w-4" />
              Connect Gmail
            </Button>
          </CardContent>
        </Card>

        {/* Data section */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Your Data</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Button
                variant="outline"
                onClick={handleExport}
                disabled={exporting}
                className="w-full"
              >
                <Download className="mr-2 h-4 w-4" />
                {exporting ? "Exporting..." : "Export my data"}
              </Button>
              <p className="mt-1 text-xs text-muted-foreground">
                Download all your data as a JSON file
              </p>
            </div>

            <div>
              <Button
                variant="destructive"
                onClick={() => setDeleteDialogOpen(true)}
                className="w-full"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete my account
              </Button>
              <p className="mt-1 text-xs text-muted-foreground">
                Permanently delete your account and all associated data
              </p>
            </div>
          </CardContent>
        </Card>
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
