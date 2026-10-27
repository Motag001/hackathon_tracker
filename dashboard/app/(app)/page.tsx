import Link from "next/link";

import { updateAlert } from "@/app/actions";
import { Flash, Section, Stat } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import type { AlertRow } from "@/lib/types";

export default async function Inbox({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const { supabase } = await requireOwner();
  const now = new Date().toISOString();
  const count = async (table: string, column: string, value: string) =>
    (await supabase.from(table).select("id", { count: "exact", head: true }).eq(column, value)).count ?? 0;

  const [alerts, gate1, gate2, gate3, gate4] = await Promise.all([
    supabase
      .from("alerts")
      .select("id,kind,title,body,event_id,read_at,snoozed_until,created_at")
      .is("read_at", null)
      .or(`snoozed_until.is.null,snoozed_until.lt."${now}"`)
      .order("created_at", { ascending: false })
      .limit(50),
    count("events", "status", "awaiting_approval"),
    count("events", "status", "plan_ready"),
    count("input_requests", "status", "pending"),
    count("events", "status", "submission_ready"),
  ]);

  return (
    <>
      <h1>Action needed</h1>
      <Flash error={error} />
      <div className="grid">
        <Link href="/events?tab=awaiting"><Stat label="Events to review" value={gate1} hint="Gate 1" /></Link>
        <Link href="/active"><Stat label="Plans to review" value={gate2} hint="Gate 2" /></Link>
        <Link href="/active"><Stat label="Inputs needed" value={gate3} hint="Gate 3" /></Link>
        <Link href="/active"><Stat label="Submissions to review" value={gate4} hint="Gate 4" /></Link>
      </div>
      <Section title="Alerts">
        {!(alerts.data ?? []).length && <p className="muted">Nothing needs you right now.</p>}
        <ul className="list">
          {((alerts.data ?? []) as AlertRow[]).map((a) => (
            <li key={a.id} className="card">
              <div className="card-head">
                <strong>
                  {a.event_id ? <Link href={`/events/${a.event_id}`}>{a.title}</Link> : a.title}
                </strong>
                <span className="muted">{fmtDate(a.created_at, true)}</span>
              </div>
              {a.body && <div className="prose muted">{a.body}</div>}
              <div className="actions">
                <form action={updateAlert}>
                  <input type="hidden" name="id" value={a.id} />
                  <input type="hidden" name="action" value="read" />
                  <button type="submit">Mark read</button>
                </form>
                <form action={updateAlert}>
                  <input type="hidden" name="id" value={a.id} />
                  <input type="hidden" name="action" value="snooze" />
                  <button type="submit">Snooze 24h</button>
                </form>
              </div>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
