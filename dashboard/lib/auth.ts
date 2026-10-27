import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { supabaseServer } from "@/lib/supabase";

/**
 * Return a Supabase client acting as the owner. The proxy signs in
 * automatically, so a missing session here means that sign-in failed. Every
 * problem goes to /status, which never signs in itself and so cannot loop.
 * RLS in the database remains the line of defence for the data.
 */
export const requireOwner = cache(async () => {
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getClaims();
  const userId = data?.claims?.sub;
  if (!userId) redirect("/status?reason=signin");

  // The app_owner policy only returns the row to the owner themself. A query
  // error here almost always means the migration has not been run yet.
  const { data: owner, error } = await supabase
    .from("app_owner")
    .select("user_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) redirect("/status?reason=setup");
  if (!owner) redirect("/status?reason=not-owner");
  return { supabase, userId };
});
