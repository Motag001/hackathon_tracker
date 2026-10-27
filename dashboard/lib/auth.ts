import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { supabaseServer } from "@/lib/supabase";

/**
 * Verify the session and that the user is the single owner. Called by every
 * page and server action; RLS in the database is the second line of defence.
 */
export const requireOwner = cache(async () => {
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getClaims();
  const userId = data?.claims?.sub;
  if (!userId) redirect("/login");

  const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  if (aal?.nextLevel === "aal2" && aal.currentLevel !== "aal2") redirect("/mfa");

  // The app_owner policy only returns the row to the owner themself. A query
  // error here almost always means the migration has not been run yet.
  const { data: owner, error } = await supabase
    .from("app_owner")
    .select("user_id")
    .eq("user_id", userId)
    .maybeSingle();
  // Server Components cannot clear cookies, so signing out here would leave
  // the session in place and loop between / and /login. The sign-out route
  // handler can clear them.
  if (error) redirect("/auth/signout?reason=setup");
  if (!owner) redirect("/auth/signout?reason=not-owner");
  return { supabase, userId };
});
