import { signIn } from "@/app/actions";
import { Flash } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="auth card">
      <h1>Sign in</h1>
      <Flash error={error} />
      <form action={signIn} className="stack">
        <label>
          Email
          <input name="email" type="email" autoComplete="username" required maxLength={320} />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required maxLength={200} />
        </label>
        <button className="primary" type="submit">Sign in</button>
      </form>
      <p className="muted">Single-user dashboard. Sign-ups are disabled.</p>
    </main>
  );
}
