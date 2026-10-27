import Link from "next/link";

import { Section, Status } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate, fmtNum, fmtUsd } from "@/lib/format";
import type { EventRow } from "@/lib/types";

const TABS = {
  awaiting: { label: "Awaiting approval", statuses: ["awaiting_approval", "deferred"] },
  below: { label: "Below threshold", statuses: ["below_threshold"] },
  filtered: { label: "Filtered out", statuses: ["filtered_out", "duplicate"] },
  decided: { label: "Decided", statuses: ["approved", "rejected"] },
  all: { label: "All", statuses: [] as string[] },
} as const;

type Tab = keyof typeof TABS;

export default async function Events({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab: raw } = await searchParams;
  const tab: Tab = raw && raw in TABS ? (raw as Tab) : "awaiting";
  const { supabase } = await requireOwner();

  let query = supabase
    .from("events")
    .select("id,source_id,title,url,status,submission_deadline,prize_text,cash_value_usd,registrants,raw,first_seen_at")
    .order("submission_deadline", { ascending: true, nullsFirst: false })
    .limit(200);
  const statuses = TABS[tab].statuses;
  if (statuses.length) query = query.in("status", [...statuses]);
  const { data: events } = await query;
  const rows = (events ?? []) as EventRow[];

  const ids = rows.map((e) => e.id);
  const { data: scores } = ids.length
    ? await supabase
        .from("scores")
        .select("event_id,total,est_hours,reason,created_at")
        .in("event_id", ids)
        .order("created_at", { ascending: false })
    : { data: [] };
  const latest = new Map<string, { total: number; est_hours: number | null; reason: string | null }>();
  for (const s of scores ?? []) if (!latest.has(s.event_id)) latest.set(s.event_id, s);

  return (
    <>
      <h1>Events</h1>
      <nav className="tabs" aria-label="Filter">
        {(Object.keys(TABS) as Tab[]).map((t) => (
          <Link key={t} href={`/events?tab=${t}`} aria-current={t === tab ? "page" : undefined}>
            {TABS[t].label}
          </Link>
        ))}
      </nav>
      <Section title={`${TABS[tab].label} (${rows.length})`}>
        {!rows.length && <p className="muted">No events here.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Event</th>
                <th>Source</th>
                <th className="num">Score</th>
                <th className="num">Hours</th>
                <th>Prize</th>
                <th>Deadline</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => {
                const s = latest.get(e.id);
                return (
                  <tr key={e.id}>
                    <td>
                      <Link href={`/events/${e.id}`}>{e.title}</Link>
                      {e.raw?.filter_reason && <div className="muted">{e.raw.filter_reason}</div>}
                      {!e.raw?.filter_reason && s?.reason && <div className="muted">{s.reason}</div>}
                    </td>
                    <td>{e.source_id}</td>
                    <td className="num">{s ? fmtNum(s.total, 0) : "—"}</td>
                    <td className="num">{s ? fmtNum(s.est_hours, 0) : "—"}</td>
                    <td>{e.cash_value_usd ? fmtUsd(e.cash_value_usd, 0) : (e.prize_text ?? "—")}</td>
                    <td>{fmtDate(e.submission_deadline)}</td>
                    <td><Status value={e.status} /></td>
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
