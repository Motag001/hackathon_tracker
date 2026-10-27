import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

// Pages that must render without a Supabase session (they explain why there
// is none). They never trigger the automatic sign-in, so they cannot loop.
const PUBLIC_PATHS = ["/status"];

function csp(nonce: string): string {
  const isDev = process.env.NODE_ENV === "development";
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
  ].join("; ");
}

/**
 * Runs before every page: sets a per-request CSP nonce and makes sure there
 * is a Supabase session for the owner.
 *
 * There is no sign-in page. When the request has no valid session, the
 * proxy signs in on the server with OWNER_EMAIL / OWNER_PASSWORD (server-only
 * Vercel variables, never sent to the browser) and stores the session in
 * cookies. Everything then runs as the owner, so row-level security and the
 * database gate triggers keep working unchanged: the agents still cannot
 * approve anything on the owner's behalf.
 *
 * Anyone who can reach this deployment can use it as the owner.
 */
export async function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const policy = csp(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  let response = NextResponse.next({ request: { headers: requestHeaders } });
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (toSet, headers) => {
          toSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request: { headers: requestHeaders } });
          toSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
          Object.entries(headers ?? {}).forEach(([k, v]) => response.headers.set(k, v));
        },
      },
    },
  );

  const redirect = (to: string) => {
    const r = NextResponse.redirect(new URL(to, request.url));
    response.cookies.getAll().forEach((c) => r.cookies.set(c));
    r.headers.set("Content-Security-Policy", policy);
    return r;
  };

  const path = request.nextUrl.pathname;
  if (!PUBLIC_PATHS.includes(path)) {
    // getClaims verifies the JWT signature; never trust an unverified session.
    const { data } = await supabase.auth.getClaims();
    if (!data?.claims) {
      const email = process.env.OWNER_EMAIL;
      const password = process.env.OWNER_PASSWORD;
      if (!email || !password) return redirect("/status?reason=config");
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        // Error details only; the credentials are never logged.
        console.warn("automatic sign-in failed", {
          name: error.name,
          code: error.code ?? null,
          status: error.status ?? null,
          message: error.message,
        });
        const code = (error.code ?? (error.status ? `http_${error.status}` : "network")).replace(
          /[^a-z0-9_]/gi,
          "",
        );
        return redirect(`/status?reason=signin&code=${code}`);
      }
    }
  }

  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
