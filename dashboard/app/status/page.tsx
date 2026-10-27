import Link from "next/link";

export const dynamic = "force-dynamic";

const DB_HELP: Record<string, string> = {
  bad_secret:
    "Supabase rejected the dashboard's token. SUPABASE_JWT_SECRET in Vercel must be the " +
    "project's JWT secret (Supabase → Settings → API → JWT Settings → Legacy JWT secret). " +
    "Update it, then redeploy.",
  network:
    "The dashboard could not reach Supabase. Check that the project is not paused, that " +
    "Settings → Network restrictions allows outside traffic, and that NEXT_PUBLIC_SUPABASE_URL " +
    "in Vercel is the project's API URL.",
};

const REASONS: Record<string, { title: string; body: string }> = {
  config: {
    title: "The dashboard is not configured yet",
    body:
      "Add two environment variables to the Vercel project (type Sensitive, Production), then " +
      "redeploy: OWNER_USER_ID, your user's UID from Supabase → Authentication → Users; and " +
      "SUPABASE_JWT_SECRET, from Supabase → Settings → API → JWT Settings (Legacy JWT secret).",
  },
  setup: {
    title: "The database is not set up",
    body:
      "Run supabase/migrations/0001_init.sql in the Supabase SQL editor, register the owner in " +
      "public.app_owner, then reload.",
  },
  "not-owner": {
    title: "OWNER_USER_ID is not registered as the owner",
    body:
      "Insert that user into public.app_owner in the Supabase SQL editor (see the README), or " +
      "correct OWNER_USER_ID in Vercel and redeploy.",
  },
};

export default async function Status({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; code?: string }>;
}) {
  const { reason = "", code = "" } = await searchParams;
  const known = REASONS[reason];
  const title = known?.title ?? "Could not read the database";
  const body =
    known?.body ??
    DB_HELP[code] ??
    `Supabase returned an error${code ? ` (${code.slice(0, 60)})` : ""}. Check the Vercel logs.`;
  return (
    <main className="auth card">
      <h1>{title}</h1>
      <p className="flash error" role="alert">{body}</p>
      <p>
        <Link href="/">Try again</Link>
      </p>
    </main>
  );
}
