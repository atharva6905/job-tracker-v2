"use client";

import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

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
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-3xl">Job Tracker</CardTitle>
          <CardDescription className="mt-2 text-base">
            Track your job applications automatically. A Chrome extension
            captures job descriptions when you apply, and email integration
            updates your status as companies respond.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          <Button size="lg" onClick={handleSignIn} className="w-full">
            Sign in with Google
          </Button>
          <p className="text-xs text-muted-foreground text-center">
            Zero manual entry. Your applications are tracked from the moment you
            start filling out a form.
          </p>
        </CardContent>
      </Card>
      {/* Placeholder for future "Approved by Google" badge */}
    </div>
  );
}
