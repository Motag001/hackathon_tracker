import { NextResponse } from "next/server";

import { supabaseServer } from "@/lib/supabase";

const REASONS = new Set(["not-owner", "setup"]);

/**
 * Clears the session cookies (a Server Component cannot) and returns to the
 * login page with an explanation. Only known reasons are passed through.
 */
export async function GET(request: Request) {
  const reason = new URL(request.url).searchParams.get("reason") ?? "";
  const supabase = await supabaseServer();
  await supabase.auth.signOut({ scope: "local" });
  const target = new URL("/login", request.url);
  if (REASONS.has(reason)) target.searchParams.set("error", reason);
  return NextResponse.redirect(target, { status: 303 });
}
