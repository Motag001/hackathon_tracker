import { Section, Stat } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate, fmtUsd, widthClass } from "@/lib/format";

export default async function Spend() {
  const { supabase } = await requireOwner();
  const monthStart = new Date();
  monthStart.setUTCDate(1);
  monthStart.setUTCHours(0, 0, 0, 0);
  const [month, settings, log] = await Promise.all([
    supabase.from("month_spend").select("*").single(),
    supabase.from("settings").select("monthly_cap_usd,soft_warn_usd,pause_usd,event_budget_usd").single(),
    supabase
      .from("spend_log")
      .select("agent,model,cost_usd,batch,purpose,input_tokens,output_tokens,cache_read_tokens,created_at")
      .gte("created_at", monthStart.toISOString())
      .order("created_at", { ascending: false })
      .limit(1000),
  ]);
  const mtd = Number(month.data?.month_to_date_usd ?? 0);
  const projected = Number(month.data?.projected_usd ?? 0);
  const cap = Number(settings.data?.monthly_cap_usd ?? 10);
  const pause = Number(settings.data?.pause_usd ?? 8);
  const warn = Number(settings.data?.soft_warn_usd ?? 5);
  const rows = log.data ?? [];

  const byKey = (key: "agent" | "model") => {
    const m = new Map<string, { cost: number; calls: number }>();
    for (const r of rows) {
      const k = String(r[key]);
      const cur = m.get(k) ?? { cost: 0, calls: 0 };
      m.set(k, { cost: cur.cost + Number(r.cost_usd), calls: cur.calls + 1 });
    }
    return [...m.entries()].sort((a, b) => b[1].cost - a[1].cost);
  };
  const cached = rows.reduce((a, r) => a + Number(r.cache_read_tokens ?? 0), 0);
  const input = rows.reduce((a, r) => a + Number(r.input_tokens ?? 0), 0);

  return (
    <>
      <h1>Anthropic spend</h1>
      <div className="grid">
        <Stat label="Month to date" value={fmtUsd(mtd)} hint={`cap ${fmtUsd(cap)}`} />
        <Stat label="Projected month end" value={fmtUsd(projected)} />
        <Stat label="Calls this month" value={rows.length} />
        <Stat label="Cache hit share" value={`${input + cached ? Math.round((cached / (input + cached)) * 100) : 0}%`} hint="of input tokens" />
      </div>
      <Section title="Budget lines">
        <div className={`bar ${mtd >= pause ? "danger" : mtd >= warn ? "warn" : ""}`}>
          <span className={widthClass(mtd / cap)} />
        </div>
        <p className="muted">
          Informational warning at {fmtUsd(warn)}; non-essential work pauses at {fmtUsd(pause)};
          hard cap {fmtUsd(cap)} (also set it in the Anthropic Console). Per-event budget{" "}
          {fmtUsd(settings.data?.event_budget_usd)}.
        </p>
      </Section>
      <div className="two">
        {(["agent", "model"] as const).map((k) => (
          <Section key={k} title={`By ${k}`}>
            <table>
              <thead><tr><th>{k}</th><th className="num">Calls</th><th className="num">Cost</th></tr></thead>
              <tbody>
                {byKey(k).map(([name, v]) => (
                  <tr key={name}><td>{name}</td><td className="num">{v.calls}</td><td className="num">{fmtUsd(v.cost, 4)}</td></tr>
                ))}
              </tbody>
            </table>
          </Section>
        ))}
      </div>
      <Section title="Recent calls">
        <div className="table-wrap">
          <table>
            <thead><tr><th>When</th><th>Agent</th><th>Model</th><th>Purpose</th><th className="num">Cost</th></tr></thead>
            <tbody>
              {rows.slice(0, 100).map((r, i) => (
                <tr key={i}>
                  <td>{fmtDate(r.created_at, true)}</td>
                  <td>{r.agent}</td>
                  <td>{r.model}{r.batch && " (batch)"}</td>
                  <td>{r.purpose}</td>
                  <td className="num">{fmtUsd(r.cost_usd, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
