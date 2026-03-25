"use client";

import { createClient } from "@/lib/supabase";

export default function LandingPage() {
  const handleSignIn = async () => {
    const supabase = createClient();
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <h1 className="font-display text-5xl font-semibold tracking-tight">
          Job Tracker
        </h1>
        <p className="mt-4 text-sm text-muted-foreground leading-relaxed max-w-sm mx-auto">
          Track your job applications automatically. A Chrome extension
          captures job descriptions when you apply, and email integration
          updates your status as companies respond.
        </p>
        <button
          onClick={handleSignIn}
          className="mt-8 inline-flex items-center justify-center rounded-md bg-foreground text-background px-8 py-3 text-sm font-medium transition-colors hover:bg-foreground/90 w-full"
        >
          Sign in with Google
        </button>
        <p className="mt-4 text-xs text-muted-foreground/60">
          Zero manual entry. Your applications are tracked from the moment you
          start filling out a form.
        </p>
      </div>
    </div>
  );
}
