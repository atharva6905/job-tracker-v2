"use client";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <h1 className="font-display text-2xl font-semibold">
          Something went wrong
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          An unexpected error occurred. Please try again.
        </p>
        <button
          onClick={reset}
          className="mt-6 rounded-md bg-foreground text-background px-6 py-2.5 text-sm font-medium transition-colors hover:bg-foreground/90"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
