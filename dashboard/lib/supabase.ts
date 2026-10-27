import "server-only";

import { createHmac } from "node:crypto";

import { createClient } from "@supabase/supabase-js";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "@/lib/env";

/**
 * There is no sign-in (owner's choice). The server acts as the owner by
 * minting a short-lived Supabase access token for OWNER_USER_ID, signed with
 * the project's JWT secret. Both values are server-only Vercel variables and
 * never reach the browser.
 *
 * Because the token carries the owner's user id, row-level security and the
 * database gate triggers (`auth.uid()` must be the owner) work unchanged:
 * the agents, which use the service-role key, still cannot approve anything.
 * Anyone who can reach the deployment can act as the owner.
 */

const TOKEN_TTL_S = 300;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class OwnerConfigError extends Error {}

function base64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

function ownerToken(userId: string, secret: string): string {
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = base64url(
    JSON.stringify({
      sub: userId,
      role: "authenticated",
      aud: "authenticated",
      iss: `${SUPABASE_URL}/auth/v1`,
      iat: now,
      exp: now + TOKEN_TTL_S,
    }),
  );
  const signature = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${signature}`;
}

/** Owner id and JWT secret from the environment, or OwnerConfigError. */
export function ownerConfig(): { userId: string; secret: string } {
  const userId = process.env.OWNER_USER_ID?.trim() ?? "";
  const secret = process.env.SUPABASE_JWT_SECRET?.trim() ?? "";
  if (!UUID.test(userId) || secret.length < 32) {
    throw new OwnerConfigError("OWNER_USER_ID or SUPABASE_JWT_SECRET is missing or invalid");
  }
  return { userId, secret };
}

/** A per-request Supabase client acting as the owner (RLS applies). */
export function supabaseServer() {
  const { userId, secret } = ownerConfig();
  return createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: `Bearer ${ownerToken(userId, secret)}` } },
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
}
