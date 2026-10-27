import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { OwnerConfigError, ownerConfig, supabaseServer } from "@/lib/supabase";

/**
 * Return a Supabase client acting as the owner. There is no sign-in: the
 * client carries a server-minted owner token (see lib/supabase.ts). Setup
 * problems go to /status, which never needs the database, so it cannot loop.
 * RLS in the database remains the line of defence for the data.
 */
export const requireOwner = cache(async () => {
  let userId: string;
  try {
    userId = ownerConfig().userId;
  } catch (e) {
    if (e instanceof OwnerConfigError) redirect("/status?reason=config");
    throw e;
  }
  const supabase = supabaseServer();

  // The app_owner policy only returns the row to the owner themself.
  const { data: owner, error } = await supabase
    .from("app_owner")
    .select("user_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) {
    // Error details only; the token and secret are never logged.
    console.warn("owner check failed", { code: error.code, message: error.message });
    const code = /JWT|jws|signature/i.test(`${error.message} ${error.code}`)
      ? "bad_secret"
      : error.code === "42P01" || error.code === "PGRST205"
        ? "setup"
        : /fetch failed|network/i.test(error.message) || !error.code
          ? "network"
          : error.code.replace(/[^a-z0-9_]/gi, "");
    redirect(code === "setup" ? "/status?reason=setup" : `/status?reason=db&code=${code}`);
  }
  if (!owner) redirect("/status?reason=not-owner");
  return { supabase, userId };
});
