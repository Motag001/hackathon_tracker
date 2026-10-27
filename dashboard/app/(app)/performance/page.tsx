import Link from "next/link";

import { Section, Stat } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtNum, fmtUsd } from "@/lib/format";

interface Perf {
  event_id: string;
  title: string;
  source_id: string;
  themes: string[];
  status: string;
  submitted_at: string | null;
  planned_hours: number;
  actual_hours: number;
  milestones_with_actuals: number;
  spent_usd: number;
  placement: number | null;
  prize_won_usd: number;
  placed: boolean;
}

function group(rows: Perf[], key: (r: Perf) => string[]) {
  const m = new Map<string, { submitted: number; placed: number; placements: number[] }>();
  for (const r of rows.filter((x) => x.submitted_at)) {
    for (const k of key(r)) {
      const g = m.get(k) ?? { submitted: 0, placed: 0, placements: [] };
      g.submitted += 1;
      if (r.placed) g.placed += 1;
      if (r.placement) g.placements.push(r.placement);
      m.set(k, g);
    }
  }
  return [...m.entries()].sort((a, b) => b[1].submitted - a[1].submitted);
}

export default async function Performance() {
  const { supabase } = await requireOwner();
  const [perf, considered, approved] = await Promise.all([
    supabase.from("event_performance").select("*"),
    supabase.from("events").select("id", { count: "exact", head: true }).neq("status", "duplicate"),
    supabase.from("decisions").select("id", { count: "exact", head: true }).eq("gate", "event").eq("decision", "approve"),
  ]);
  const rows = (perf.data ?? []) as Perf[];
  const submitted = rows.filter((r) => r.submitted_at);
  const placed = submitted.filter((r) => r.placed);
  const hours = rows.reduce((a, r) => a + Number(r.actual_hours), 0);
  const prize = rows.reduce((a, r) => a + Number(r.prize_won_usd), 0);
  const spend = submitted.reduce((a, r) => a + Number(r.spent_usd), 0);
  const withActuals = rows.filter((r) => r.milestones_with_actuals > 0 && Number(r.planned_hours) > 0);
  const accuracy = withActuals.length
    ? withActuals.reduce((a, r) => a + Number(r.actual_hours) / Number(r.planned_hours), 0) / withActuals.length
    : null;

  return (
    <>
      <h1>Performance</h1>
      <div className="grid">
        <Stat label="Considered" value={considered.count ?? 0} />
        <Stat label="Approved" value={approved.count ?? 0} />
        <Stat label="Submitted" value={submitted.length} />
        <Stat label="Placed" value={placed.length} hint={submitted.length ? `${Math.round((placed.length / submitted.length) * 100)}% win rate` : undefined} />
        <Stat label="Hours invested" value={fmtNum(hours)} />
        <Stat label="Prize money" value={fmtUsd(prize, 0)} hint={hours ? `${fmtUsd(prize / hours)}/hour` : undefined} />
        <Stat label="Cost per submission" value={submitted.length ? fmtUsd(spend / submitted.length) : "—"} />
        <Stat label="Estimate accuracy" value={accuracy ? `×${accuracy.toFixed(2)}` : "—"} hint="actual ÷ planned hours" />
      </div>
      <div className="two">
        <Section title="By source">
          <GroupTable groups={group(rows, (r) => [r.source_id])} />
        </Section>
        <Section title="By theme">
          <GroupTable groups={group(rows, (r) => (r.themes?.length ? r.themes : ["(none)"]))} />
        </Section>
      </div>
      <Section title="Events">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Event</th><th className="num">Planned h</th><th className="num">Actual h</th><th className="num">Spend</th><th className="num">Place</th><th className="num">Prize</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.event_id}>
                  <td><Link href={`/events/${r.event_id}`}>{r.title}</Link></td>
                  <td className="num">{fmtNum(r.planned_hours)}</td>
                  <td className="num">{fmtNum(r.actual_hours)}</td>
                  <td className="num">{fmtUsd(r.spent_usd)}</td>
                  <td className="num">{r.placement ?? "—"}</td>
                  <td className="num">{fmtUsd(r.prize_won_usd, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}

function GroupTable({ groups }: { groups: [string, { submitted: number; placed: number; placements: number[] }][] }) {
  if (!groups.length) return <p className="muted">No submissions yet.</p>;
  return (
    <table>
      <thead><tr><th>Group</th><th className="num">Submitted</th><th className="num">Win rate</th><th className="num">Avg place</th></tr></thead>
      <tbody>
        {groups.map(([k, g]) => (
          <tr key={k}>
            <td>{k}</td>
            <td className="num">{g.submitted}</td>
            <td className="num">{Math.round((g.placed / g.submitted) * 100)}%</td>
            <td className="num">{g.placements.length ? fmtNum(g.placements.reduce((a, b) => a + b, 0) / g.placements.length) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
