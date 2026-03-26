"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAPI } from "@/lib/api";
import type { EmailAccount } from "@/lib/types";
import { Check, X } from "lucide-react";

const CHECKLIST_KEY = "checklist_dismissed";

export function SetupChecklist() {
  const [dismissed, setDismissed] = useState(true);
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

    fetchAPI<EmailAccount[]>("/gmail/accounts")
      .then((accounts) => setGmailConnected(accounts.length > 0))
      .catch(() => {});

    const extEl = document.getElementById("job-tracker-v2-ext");
    setExtensionDetected(!!extEl);

    setLoading(false);
  }, []);

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

  const steps = [
    {
      done: gmailConnected,
      label: "Connect Gmail",
      detail: gmailConnected ? (
        "Connected"
      ) : (
        <>
          <Link href="/settings" className="text-accent-gold hover:underline">
            Go to settings
          </Link>{" "}
          to connect your Gmail account
        </>
      ),
    },
    {
      done: extensionDetected,
      label: "Install Chrome extension",
      detail: extensionDetected
        ? "Detected"
        : "Install the Job Tracker extension from the Chrome Web Store",
    },
    {
      done: false,
      label: "Apply to a job",
      detail:
        "When you start a job application, the extension will capture it automatically",
    },
  ];

  return (
    <div className="mb-8 border border-border/50 rounded-lg px-5 py-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-display text-lg font-semibold">Get started</h3>
        <button
          type="button"
          onClick={handleDismiss}
          className="p-1 text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex flex-col gap-2.5">
        {steps.map((step, i) => (
          <div key={i} className="flex items-start gap-3">
            <div
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                step.done
                  ? "bg-accent-gold/20 text-accent-gold"
                  : "border border-border text-transparent"
              }`}
            >
              {step.done && <Check className="h-3 w-3" />}
            </div>
            <div>
              <p className="text-sm font-medium">{step.label}</p>
              <p className="text-xs text-muted-foreground">{step.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
