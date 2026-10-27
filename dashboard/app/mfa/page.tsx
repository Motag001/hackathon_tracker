import { signOut, verifyMfa } from "@/app/actions";
import { Flash } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Mfa({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="auth card">
      <h1>Two-factor check</h1>
      <Flash error={error} />
      <form action={verifyMfa} className="stack">
        <label>
          6-digit code from your authenticator app
          <input name="code" inputMode="numeric" pattern="\d{6}" autoComplete="one-time-code" required maxLength={6} />
        </label>
        <button className="primary" type="submit">Verify</button>
      </form>
      <form action={signOut}>
        <button type="submit" className="link">Use a different account</button>
      </form>
    </main>
  );
}
