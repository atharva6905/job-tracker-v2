"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { fetchAPI } from "@/lib/api";
import type { EmailAccount } from "@/lib/types";
import { CheckCircle2, Circle, X } from "lucide-react";

const CHECKLIST_KEY = "checklist_dismissed";

export function SetupChecklist() {
  const [dismissed, setDismissed] = useState(true); // default hidden until checked
  const [gmailConnected, setGmailConnected] = useState(false);
  const [extensionDetected, setExtensionDetected] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(CHECKLIST_KEY);
    if (stored === "true") {
      setDismissed(true);
      setLoading(false);
      return;
    }
    setDismissed(false);

    // Check Gmail connection
    fetchAPI<EmailAccount[]>("/gmail/accounts")
      .then((accounts) => setGmailConnected(accounts.length > 0))
      .catch(() => {});

    // Check extension presence
    const extEl = document.getElementById("job-tracker-v2-ext");
    setExtensionDetected(!!extEl);

    setLoading(false);
  }, []);

  // Auto-dismiss when both steps complete
  useEffect(() => {
    if (gmailConnected && extensionDetected && !dismissed) {
      localStorage.setItem(CHECKLIST_KEY, "true");
      setDismissed(true);
    }
  }, [gmailConnected, extensionDetected, dismissed]);

  if (loading || dismissed) return null;

  const handleDismiss = () => {
    localStorage.setItem(CHECKLIST_KEY, "true");
    setDismissed(true);
  };

  return (
    <Card className="mb-6">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-lg">Get started</CardTitle>
        <Button variant="ghost" size="icon" onClick={handleDismiss}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3">
          {gmailConnected ? (
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
          ) : (
            <Circle className="h-5 w-5 text-muted-foreground shrink-0" />
          )}
          <div>
            <p className="text-sm font-medium">Connect Gmail</p>
            {gmailConnected ? (
              <p className="text-xs text-muted-foreground">Connected</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                <Link href="/settings" className="underline">
                  Go to settings
                </Link>{" "}
                to connect your Gmail account
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {extensionDetected ? (
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
          ) : (
            <Circle className="h-5 w-5 text-muted-foreground shrink-0" />
          )}
          <div>
            <p className="text-sm font-medium">Install Chrome extension</p>
            {extensionDetected ? (
              <p className="text-xs text-muted-foreground">Detected</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Install the Job Tracker extension from the Chrome Web Store
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Circle className="h-5 w-5 text-muted-foreground shrink-0" />
          <div>
            <p className="text-sm font-medium">Apply to a job</p>
            <p className="text-xs text-muted-foreground">
              When you start a job application, the extension will capture it
              automatically
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
