import Link from "next/link";

export const dynamic = "force-dynamic";

const SIGN_IN_HELP: Record<string, string> = {
  invalid_credentials:
    "OWNER_EMAIL or OWNER_PASSWORD in Vercel does not match the Supabase user. Update the " +
    "Vercel variables (or reset the password in Supabase → Authentication → Users), then redeploy.",
  email_not_confirmed:
    "The owner's email is not confirmed. In Supabase → Authentication → Users, open the user " +
    "and confirm it (or recreate it with Auto Confirm User ticked).",
  over_request_rate_limit: "Supabase is rate limiting sign-ins. Wait a minute and reload.",
  network:
    "The dashboard could not reach Supabase. Check that the project is not paused, that " +
    "Settings → Network restrictions allows outside traffic, and that NEXT_PUBLIC_SUPABASE_URL " +
    "in Vercel is the project's API URL.",
};

const REASONS: Record<string, { title: string; body: string }> = {
  config: {
    title: "Owner credentials are not configured",
    body:
      "Add OWNER_EMAIL and OWNER_PASSWORD to the Vercel project's environment variables " +
      "(type Sensitive, Production only), then redeploy.",
  },
  setup: {
    title: "The database is not set up",
    body:
      "Run supabase/migrations/0001_init.sql in the Supabase SQL editor, register the owner in " +
      "public.app_owner, then reload.",
  },
  "not-owner": {
    title: "This user is not registered as the owner",
    body:
      "Insert the OWNER_EMAIL user into public.app_owner in the Supabase SQL editor (see the " +
      "README), then reload.",
  },
};

export default async function Status({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; code?: string }>;
}) {
  const { reason = "", code = "" } = await searchParams;
  const known = REASONS[reason];
  const title = known?.title ?? "Could not sign in to Supabase";
  const body =
    known?.body ??
    SIGN_IN_HELP[code] ??
    `Supabase refused the automatic sign-in${code ? ` (${code.slice(0, 60)})` : ""}.`;
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
