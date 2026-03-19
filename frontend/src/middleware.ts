import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const PROTECTED_PATHS = ["/dashboard", "/applications", "/settings"];

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return supabaseResponse;

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: { name: string; value: string; options?: object }[]) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value)
        );
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options as never)
        );
      },
    },
  });

  // IMPORTANT: no logic between createServerClient and getUser()
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  // Helper: create a redirect that carries any refreshed session cookies
  const redirectWithCookies = (destination: URL) => {
    const redirect = NextResponse.redirect(destination);
    supabaseResponse.cookies
      .getAll()
      .forEach((c) => redirect.cookies.set(c.name, c.value, c));
    return redirect;
  };

  // Redirect authenticated users from landing to dashboard
  if (pathname === "/" && user) {
    return redirectWithCookies(new URL("/dashboard", request.url));
  }

  // Protect routes
  const isProtected = PROTECTED_PATHS.some((p) => pathname.startsWith(p));
  if (isProtected && !user) {
    return redirectWithCookies(new URL("/", request.url));
  }

  // IMPORTANT: must return supabaseResponse so refreshed cookies reach the browser
  return supabaseResponse;
}

export const config = {
  matcher: ["/", "/dashboard/:path*", "/applications/:path*", "/settings/:path*"],
};
