import { createClient } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export async function fetchAPI<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    console.error("[fetchAPI] No session — user is signed in but getSession() returned null. Check NEXT_PUBLIC_SUPABASE_URL and cookie state.");
    throw new Error("Not authenticated");
  }

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
    ...options.headers,
  };

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    throw new Error("Unauthorized");
  }

  if (res.status === 204) {
    return undefined as T;
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    console.error(`[fetchAPI] ${res.status} from ${API_BASE}${path}:`, body);
    throw new Error(body.detail || `API error: ${res.status}`);
  }

  return res.json();
}
