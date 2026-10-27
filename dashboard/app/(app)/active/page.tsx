import Link from "next/link";

import { Section, Status } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate, hoursUntil } from "@/lib/format";
import type { EventRow } from "@/lib/types";

const ACTIVE = [
  "approved", "planning", "plan_ready", "plan_approved", "building", "awaiting_input",
  "paused_budget", "in_review", "submission_ready", "submitted", "results_in",
];

export default async function Active() {
  const { supabase } = await requireOwner();
  const { data } = await supabase
    .from("events")
    .select("id,title,status,submission_deadline,source_id")
    .in("status", ACTIVE)
    .order("submission_deadline", { ascending: true, nullsFirst: false });
  const rows = (data ?? []) as Pick<EventRow, "id" | "title" | "status" | "submission_deadline" | "source_id">[];
  const { data: pending } = await supabase
    .from("input_requests")
    .select("event_id")
    .eq("status", "pending");
  const waiting = new Map<string, number>();
  for (const p of pending ?? []) waiting.set(p.event_id, (waiting.get(p.event_id) ?? 0) + 1);

  return (
    <>
      <h1>Active events</h1>
      <Section title={`In progress (${rows.length})`}>
        {!rows.length && <p className="muted">Nothing in progress. Approve an event to start.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Event</th><th>Stage</th><th>Inputs pending</th><th>Deadline</th></tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const h = hoursUntil(e.submission_deadline);
                return (
                  <tr key={e.id}>
                    <td><Link href={`/events/${e.id}`}>{e.title}</Link></td>
                    <td><Status value={e.status} /></td>
                    <td>{waiting.get(e.id) ?? 0}</td>
                    <td className={h !== null && h < 48 ? "fail" : ""}>
                      {fmtDate(e.submission_deadline, true)}
                      {h !== null && h > 0 && h < 48 && ` (${Math.round(h)}h left)`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
