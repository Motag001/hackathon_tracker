import Link from "next/link";
import { cookies } from "next/headers";
import { z } from "zod";

import { confirmMfa } from "@/app/actions";
import { Flash, Section } from "@/components/ui";
import { requireOwner } from "@/lib/auth";

const pendingSchema = z.object({
  id: z.string().min(1).max(100),
  qr: z.string().startsWith("data:image/svg+xml"),
  secret: z.string().min(16).max(128),
});

export default async function EnrollMfa({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  await requireOwner();
  const raw = (await cookies()).get("mfa_enroll")?.value;
  let pending: z.infer<typeof pendingSchema> | null = null;
  try {
    pending = raw ? pendingSchema.parse(JSON.parse(raw)) : null;
  } catch {
    pending = null;
  }
  if (!pending) {
    return (
      <Section title="Authenticator setup">
        <p>No enrolment in progress, or it expired. <Link href="/settings">Start again from settings</Link>.</p>
      </Section>
    );
  }
  return (
    <Section title="Authenticator setup">
      <Flash error={error} />
      <p>Scan this code with your authenticator app, then enter the 6-digit code it shows.</p>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="qr" src={pending.qr} alt="TOTP QR code" />
      <p className="muted">Or enter this secret manually: <code>{pending.secret}</code></p>
      <form action={confirmMfa} className="stack">
        <input type="hidden" name="factor" value={pending.id} />
        <label>Code<input name="code" inputMode="numeric" pattern="\d{6}" maxLength={6} required /></label>
        <div className="actions"><button className="primary" type="submit">Verify and enable</button></div>
      </form>
    </Section>
  );
}
