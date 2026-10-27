import { saveSettings, toggleSkill, updateSource } from "@/app/actions";
import { Flash, Section } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate } from "@/lib/format";

const PROFILE_EXAMPLE = {
  country: "Nigeria",
  hours_per_day: 4,
  skills: ["python", "data analysis", "machine learning"],
  languages: ["python", "sql"],
  tools: ["pandas", "scikit-learn", "fastapi"],
  cloud_accounts: [],
  hardware: [],
  datasets: [],
  interests: ["AI for social good", "agriculture", "fintech"],
};

export default async function Settings({ searchParams }: { searchParams: Promise<{ error?: string; ok?: string }> }) {
  const { error, ok } = await searchParams;
  const { supabase } = await requireOwner();
  const [settings, sources, skills] = await Promise.all([
    supabase.from("settings").select("*").eq("id", 1).single(),
    supabase.from("sources").select("*").order("id"),
    supabase.from("skills").select("id,name,enabled,usage_count,success_count").order("id"),
  ]);
  const s = settings.data;
  const profile = s?.profile && Object.keys(s.profile).length ? s.profile : PROFILE_EXAMPLE;

  return (
    <>
      <h1>Settings</h1>
      <Flash error={error} ok={ok} />
      <Section title="Selection and budgets">
        <form action={saveSettings} className="stack">
          <div className="grid">
            <label>Surface threshold (0-100)<input name="surface_threshold" type="number" min="0" max="100" step="1" defaultValue={s?.surface_threshold ?? 65} /></label>
            <label>Per-event budget (USD)<input name="event_budget_usd" type="number" min="0.1" max="10" step="0.1" defaultValue={s?.event_budget_usd ?? 1.5} /></label>
            <label>Minimum prize (USD)<input name="min_prize_usd" type="number" min="0" step="1" defaultValue={s?.min_prize_usd ?? 50} /></label>
            <label>Maximum effort (hours)<input name="max_effort_hours" type="number" min="1" max="500" step="1" defaultValue={s?.max_effort_hours ?? 72} /></label>
          </div>
          <label>
            Your profile (JSON: country, hours_per_day, skills, languages, tools, cloud_accounts,
            hardware, datasets, interests, notes). Agents read this to judge fit; do not put secrets here.
            <textarea className="code" name="profile" defaultValue={JSON.stringify(profile, null, 2)} maxLength={20000} />
          </label>
          <p className="muted">Threshold changes are applied on the next intake run without re-scoring.</p>
          <div className="actions"><button className="primary" type="submit">Save</button></div>
        </form>
      </Section>

      <Section title="Sources">
        <p className="muted">Each source stays off until you have read its terms of use and confirmed below.</p>
        <table>
          <thead><tr><th>Source</th><th>Status</th><th>Last run</th><th>Change</th></tr></thead>
          <tbody>
            {(sources.data ?? []).map((src) => (
              <tr key={src.id}>
                <td>{src.name}<div className="muted">{src.base_url}</div></td>
                <td>
                  {src.enabled ? <span className="pass">enabled</span> : <span className="muted">disabled</span>}
                  {src.terms_reviewed_at && <div className="muted">terms reviewed {fmtDate(src.terms_reviewed_at)}</div>}
                </td>
                <td>
                  {fmtDate(src.last_run_at, true)}
                  {src.last_status === "error" && <div className="fail">{src.last_error}</div>}
                </td>
                <td>
                  <form action={updateSource} className="stack">
                    <input type="hidden" name="id" value={src.id} />
                    <input type="hidden" name="enabled" value={src.enabled ? "false" : "true"} />
                    {!src.enabled && (
                      <>
                        <label className="inline"><input type="checkbox" name="terms_reviewed" value="on" /> I reviewed this site&apos;s terms</label>
                        <input name="terms_notes" placeholder="Notes on the terms" maxLength={2000} defaultValue={src.terms_notes ?? ""} />
                      </>
                    )}
                    <button type="submit">{src.enabled ? "Disable" : "Enable"}</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Skills">
        <table>
          <thead><tr><th>Skill</th><th className="num">Used</th><th className="num">Success</th><th></th></tr></thead>
          <tbody>
            {(skills.data ?? []).map((sk) => (
              <tr key={sk.id}>
                <td>{sk.name}<div className="muted">{sk.id}</div></td>
                <td className="num">{sk.usage_count}</td>
                <td className="num">{sk.usage_count ? `${Math.round((sk.success_count / sk.usage_count) * 100)}%` : "—"}</td>
                <td>
                  <form action={toggleSkill}>
                    <input type="hidden" name="id" value={sk.id} />
                    <input type="hidden" name="enabled" value={sk.enabled ? "false" : "true"} />
                    <button type="submit">{sk.enabled ? "Disable" : "Enable"}</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!(skills.data ?? []).length && <p className="muted">Run the &quot;sync-skills&quot; workflow command to load the registry.</p>}
      </Section>

    </>
  );
}
