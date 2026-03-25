import Link from "next/link";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-4">
      <div className="w-full max-w-md text-center">
        <h1 className="font-display text-2xl font-semibold">Page not found</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          The page you are looking for does not exist.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 inline-block rounded-md border border-border/50 px-6 py-2.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
