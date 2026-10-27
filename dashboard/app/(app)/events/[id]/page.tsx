import Link from "next/link";
import { notFound } from "next/navigation";

import {
  answerInput,
  decide,
  recordResult,
  saveLearning,
  saveSubmission,
  updateMilestone,
} from "@/app/actions";
import { Flash, List, Prose, Section, Stat, Status } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate, fmtNum, fmtUsd, safeHref, widthClass } from "@/lib/format";
import type { EventRow, Factor, Json, ScoreRow } from "@/lib/types";

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const GATE1 = ["awaiting_approval", "deferred", "below_threshold"];

function Hidden({ name, value }: { name: string; value: string }) {
  return <input type="hidden" name={name} value={value} />;
}

export default async function EventPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const { error } = await searchParams;
  if (!UUID.test(id)) notFound();
  const { supabase } = await requireOwner();

  const latest = (table: string, order = "created_at") =>
    supabase.from(table).select("*").eq("event_id", id).order(order, { ascending: false }).limit(1).maybeSingle();

  const [ev, rules, score, plan, inputs, artifacts, submission, result, learning, spend, settings, decisions] =
    await Promise.all([
      supabase.from("events").select("*").eq("id", id).maybeSingle(),
      latest("event_rules"),
      latest("scores"),
      latest("plans", "version"),
      supabase.from("input_requests").select("*").eq("event_id", id).order("created_at"),
      supabase.from("artifacts").select("id,path,skill_id,size_bytes,milestone_id,created_at").eq("event_id", id).order("path"),
      latest("submissions", "version"),
      supabase.from("results").select("*").eq("event_id", id).maybeSingle(),
      supabase.from("learnings").select("*").eq("event_id", id).maybeSingle(),
      supabase.from("event_spend").select("spent_usd").eq("event_id", id).maybeSingle(),
      supabase.from("settings").select("event_budget_usd").eq("id", 1).single(),
      supabase.from("decisions").select("gate,decision,reason,created_at").eq("event_id", id).order("created_at", { ascending: false }),
    ]);
  const e = ev.data as (EventRow & Row) | null;
  if (!e) notFound();

  const p = plan.data as Row | null;
  const [milestones, datasets] = p
    ? await Promise.all([
        supabase.from("milestones").select("*").eq("plan_id", p.id).order("seq"),
        supabase.from("datasets").select("*").eq("plan_id", p.id),
      ])
    : [{ data: [] }, { data: [] }];

  const r = (rules.data ?? {}) as Row;
  const s = score.data as ScoreRow | null;
  const sub = submission.data as Row | null;
  const spent = Number(spend.data?.spent_usd ?? 0);
  const budget = Number(settings.data?.event_budget_usd ?? 1.5);
  const pending = ((inputs.data ?? []) as Row[]).filter((i) => i.status === "pending");
  const answered = ((inputs.data ?? []) as Row[]).filter((i) => i.status !== "pending");
  const link = safeHref(e.url);

  return (
    <>
      <p><Link href="/events">← Events</Link></p>
      <h1>{e.title}</h1>
      <Flash error={error} />
      <div className="grid">
        <Stat label="Status" value={<Status value={e.status} />} />
        <Stat label="Score" value={s ? fmtNum(s.total, 0) : "—"} hint={s?.model_version} />
        <Stat label="Est. hours" value={s ? fmtNum(s.est_hours, 0) : "—"} />
        <Stat label="Prize" value={e.cash_value_usd ? fmtUsd(e.cash_value_usd, 0) : (e.prize_text ?? "—")} />
        <Stat label="Deadline" value={fmtDate(e.submission_deadline)} />
        <Stat label="Spend" value={fmtUsd(spent)} hint={`of ${fmtUsd(budget)} budget`} />
      </div>
      <p>
        {link ? <a href={link} target="_blank" rel="noopener noreferrer nofollow">{e.url}</a> : e.url}
        {" · "}{e.source_id}{e.registrants != null && ` · ${e.registrants} registrants`}
      </p>

      {GATE1.includes(e.status) && (
        <Section title="Gate 1 · Event decision">
          <form action={decide} className="stack">
            <Hidden name="event_id" value={id} />
            <Hidden name="gate" value="event" />
            <label>
              Reason (required to reject; it feeds back into scoring)
              <textarea name="reason" maxLength={4000} />
            </label>
            <div className="actions">
              <button className="primary" name="decision" value="approve">Approve</button>
              <button name="decision" value="defer">Defer</button>
              <button className="danger" name="decision" value="reject">Reject</button>
            </div>
          </form>
        </Section>
      )}

      {s && (
        <Section title="Score breakdown" aside={<span className="muted">{s.reason}</span>}>
          <div className="two">
            <table>
              <thead><tr><th>Factor</th><th className="num">Points</th><th>Why</th></tr></thead>
              <tbody>
                {Object.entries(s.factors)
                  .filter(([k]) => !k.startsWith("_"))
                  .map(([k, raw]) => {
                    const f = raw as Factor;
                    return (
                      <tr key={k}>
                        <td>
                          {k.replaceAll("_", " ")}
                          <div className="bar"><span className={widthClass(f.value)} /></div>
                        </td>
                        <td className="num">{fmtNum(f.points)} / {f.weight}</td>
                        <td>{f.reason}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            <table>
              <thead><tr><th>Hard filter</th><th>Result</th></tr></thead>
              <tbody>
                {s.hard_filters.map((f) => (
                  <tr key={f.name}>
                    <td>{f.name.replaceAll("_", " ")}</td>
                    <td className={f.passed ? "pass" : "fail"}>{f.passed ? "✓" : "✗"} {f.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {rules.data && (
        <Section title="Rules" aside={<span className="muted">read {fmtDate(r.fetched_at, true)}</span>}>
          <Prose text={r.summary} />
          <div className="two">
            <div>
              <h3>AI policy: {r.ai_policy}</h3>
              <Prose text={r.ai_policy_notes} />
              {r.disclosure_format && <><h3>Required disclosure format</h3><Prose text={r.disclosure_format} /></>}
              <h3>Solo entry</h3>
              <p>{r.solo_allowed === null ? "Not stated" : r.solo_allowed ? "Allowed" : "Not allowed"}</p>
              <h3>Requirements</h3>
              <List items={r.requirements as string[]} />
            </div>
            <div>
              <h3>Judging criteria</h3>
              <List items={(r.judging_criteria as Row[] | null)?.map((c) =>
                `${c.name}${c.weight_percent ? ` (${c.weight_percent}%)` : ""}${c.description ? `: ${c.description}` : ""}`)} />
              <h3>Risks</h3>
              <List items={r.risks as string[]} />
              <h3>Ambiguities to clarify</h3>
              <List items={r.ambiguities as string[]} />
            </div>
          </div>
        </Section>
      )}

      {p && (
        <Section title={`Plan v${p.version}`} aside={<Status value={p.status} />}>
          <div className="two">
            <div>
              <h3>Problem</h3><Prose text={p.problem} />
              <h3>Angle</h3><Prose text={p.angle} />
              <h3>Summary</h3><Prose text={p.summary} />
            </div>
            <div>
              <h3>Local context and sources</h3><Prose text={p.local_context} />
              <h3>Risks</h3><List items={p.risks as string[]} />
              {!!(p.warnings as string[])?.length && (
                <div className="callout"><strong>Checks</strong><List items={p.warnings as string[]} /></div>
              )}
            </div>
          </div>
          <h3>Milestones · {fmtNum(p.total_hours)}h planned</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>#</th><th>Milestone</th><th className="num">Est.</th><th className="num">Actual</th><th>Skills</th><th>Status</th><th>Update</th></tr>
              </thead>
              <tbody>
                {((milestones.data ?? []) as Row[]).map((m) => (
                  <tr key={m.id}>
                    <td>{m.seq}</td>
                    <td>
                      <strong>{m.title}</strong>
                      {m.needs_top_tier && <span className="badge warn"> top tier</span>}
                      <Prose text={m.description} />
                      {m.notes && <details><summary>Notes</summary><Prose text={m.notes} /></details>}
                      {m.test_report && (
                        <details>
                          <summary className={m.test_report.ok ? "pass" : "fail"}>
                            Tests: {m.test_report.passed} passed, {m.test_report.failed} failed
                          </summary>
                          <pre className="prose">{m.test_report.output_tail}</pre>
                        </details>
                      )}
                    </td>
                    <td className="num">{fmtNum(m.est_hours)}</td>
                    <td className="num">{fmtNum(m.actual_hours)}</td>
                    <td>{(m.skills as string[]).join(", ")}</td>
                    <td><Status value={m.status} /></td>
                    <td>
                      {p.status === "approved" && (
                        <form action={updateMilestone} className="inline">
                          <Hidden name="id" value={m.id} />
                          <Hidden name="event_id" value={id} />
                          <input name="actual_hours" type="number" step="0.25" min="0" max="500" placeholder="hours" aria-label="Actual hours" />
                          <select name="status" defaultValue={m.status === "drafted" ? "done" : m.status} aria-label="Status">
                            <option value="done">done</option>
                            <option value="drafted">drafted</option>
                            <option value="skipped">skip</option>
                            <option value="pending">retry</option>
                          </select>
                          <button type="submit">Save</button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!!(datasets.data ?? []).length && (
            <>
              <h3>Datasets</h3>
              <table>
                <thead><tr><th>Name</th><th>Source</th><th>License</th><th>License check</th></tr></thead>
                <tbody>
                  {((datasets.data ?? []) as Row[]).map((d) => (
                    <tr key={d.id}>
                      <td>{d.name}{d.owner_data && <span className="badge warn"> your data</span>}</td>
                      <td>{safeHref(d.url) ? <a href={safeHref(d.url)!} target="_blank" rel="noopener noreferrer nofollow">{d.source}</a> : d.source}</td>
                      <td>{d.license ?? "unknown"}</td>
                      <td className={d.license_ok ? "pass" : "fail"}>{d.license_ok ? "permissive" : d.license_ok === false ? "restricted" : "needs your check"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3>AI-use disclosure draft</h3>
          <Prose text={p.disclosure_draft} />

          {e.status === "plan_ready" && p.status === "ready" && (
            <form action={decide} className="stack">
              <h3>Gate 2 · Plan decision</h3>
              <Hidden name="event_id" value={id} />
              <Hidden name="gate" value="plan" />
              <Hidden name="plan_id" value={p.id} />
              <label>
                Notes (required to send back for revision)
                <textarea name="reason" maxLength={4000} />
              </label>
              <div className="actions">
                <button className="primary" name="decision" value="approve">Approve plan</button>
                <button name="decision" value="revise">Send back for revision</button>
                <button className="danger" name="decision" value="reject">Drop event</button>
              </div>
            </form>
          )}
        </Section>
      )}

      {!!(inputs.data ?? []).length && (
        <Section title={`Gate 3 · Inputs (${pending.length} pending)`}>
          <p className="callout">
            Never paste passwords, API keys or payment details. For credentials, set them up
            yourself (GitHub or Vercel settings) and answer &quot;done&quot;.
          </p>
          {pending.map((i) => (
            <form key={i.id} action={answerInput} className="stack card">
              <Hidden name="id" value={i.id} />
              <Hidden name="event_id" value={id} />
              <strong>{i.key.replaceAll("_", " ")} <span className="badge info">{i.kind.replaceAll("_", " ")}</span></strong>
              <Prose text={i.description} />
              <textarea name="response" maxLength={10000} aria-label="Your response" />
              <div className="actions">
                <button className="primary" name="action" value="answer">Send</button>
                <button name="action" value="decline">Decline</button>
              </div>
            </form>
          ))}
          {!!answered.length && (
            <details>
              <summary>Answered ({answered.length})</summary>
              <ul className="list">
                {answered.map((i) => (
                  <li key={i.id}><strong>{i.key}</strong> [{i.status}]: {i.response ?? "—"}</li>
                ))}
              </ul>
            </details>
          )}
        </Section>
      )}

      {!!(artifacts.data ?? []).length && (
        <Section title="Artifacts">
          <p className="muted">Drafts produced by the Builder. Review everything before you use it.</p>
          <table>
            <thead><tr><th>File</th><th>Skill</th><th className="num">Size</th><th>Created</th></tr></thead>
            <tbody>
              {((artifacts.data ?? []) as Row[]).map((a) => (
                <tr key={a.id}>
                  <td><a href={`/artifacts/${a.id}`}>{a.path}</a></td>
                  <td>{a.skill_id}</td>
                  <td className="num">{(a.size_bytes / 1024).toFixed(1)} KB</td>
                  <td>{fmtDate(a.created_at, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {sub && <SubmissionPanel id={id} status={e.status} sub={sub} />}

      {["submitted", "results_in"].includes(e.status) && (
        <Section title="Results">
          <form action={recordResult} className="stack">
            <Hidden name="event_id" value={id} />
            <div className="two">
              <label>Placement (number)<input name="placement" type="number" min="1" defaultValue={result.data?.placement ?? ""} /></label>
              <label>Placement (text, e.g. &quot;Honourable mention&quot;)<input name="placement_text" maxLength={200} defaultValue={result.data?.placement_text ?? ""} /></label>
              <label>Prize won (USD)<input name="prize_won_usd" type="number" min="0" step="0.01" defaultValue={result.data?.prize_won_usd ?? ""} /></label>
            </div>
            <label>Judge feedback<textarea name="judge_feedback" maxLength={20000} defaultValue={result.data?.judge_feedback ?? ""} /></label>
            <label>Platform notes<textarea name="platform_notes" maxLength={5000} defaultValue={result.data?.platform_notes ?? ""} /></label>
            <div className="actions"><button className="primary" type="submit">Save results</button></div>
          </form>
        </Section>
      )}

      {(learning.data || e.status === "results_in") && (
        <Section title="What I learned" aside={learning.data ? <Status value={learning.data.status} /> : undefined}>
          <form action={saveLearning} className="stack">
            <Hidden name="event_id" value={id} />
            <label>What went well<textarea name="went_well" maxLength={5000} defaultValue={learning.data?.went_well ?? ""} /></label>
            <label>What I would change<textarea name="would_change" maxLength={5000} defaultValue={learning.data?.would_change ?? ""} /></label>
            <label>What I&apos;d carry forward<textarea name="carry_forward" maxLength={5000} defaultValue={learning.data?.carry_forward ?? ""} /></label>
            <div className="actions">
              <button name="approve" value="no">Save draft</button>
              <button className="primary" name="approve" value="yes">Save and approve</button>
            </div>
          </form>
        </Section>
      )}

      <Section title="Spend on this event">
        <div className={`bar ${spent > budget ? "danger" : spent > budget * 0.8 ? "warn" : ""}`}>
          <span className={widthClass(spent / budget)} />
        </div>
        <p className="muted">{fmtUsd(spent, 4)} of {fmtUsd(budget)} per-event budget.</p>
      </Section>

      {!!(decisions.data ?? []).length && (
        <Section title="Decision log">
          <List items={((decisions.data ?? []) as Row[]).map((d) =>
            `${fmtDate(d.created_at, true)} · ${d.gate}: ${d.decision}${d.reason ? ` — ${d.reason}` : ""}`)} />
        </Section>
      )}
    </>
  );
}

function SubmissionPanel({ id, status, sub }: { id: string; status: string; sub: Row }) {
  const pkg = (sub.package ?? {}) as Record<string, Json>;
  const issues = (sub.blocking_issues ?? []) as string[];
  const checklist = (sub.checklist ?? []) as Row[];
  const fields = (pkg.form_fields ?? []) as Row[];
  return (
    <Section title={`Submission package v${sub.version}`} aside={<Status value={sub.status} />}>
      {!!issues.length && (
        <div className="callout danger">
          <strong>Blocking issues — fix or consciously accept before submitting</strong>
          <List items={issues} />
        </div>
      )}
      <h3>{String(pkg.project_name ?? "")}</h3>
      <p className="muted">{String(pkg.tagline ?? "")}</p>
      <div className="two">
        <div><h3>Description</h3><Prose text={String(pkg.description_markdown ?? "")} /></div>
        <div><h3>Demo script</h3><Prose text={String(pkg.demo_script ?? "")} /></div>
      </div>
      <h3>Form fields</h3>
      <List items={fields.map((f) => `${f.field}: ${f.value}`)} />
      <h3>Screenshots to capture yourself</h3>
      <List items={pkg.screenshots_needed as string[]} />
      <h3>Checklist</h3>
      <table>
        <tbody>
          {checklist.map((c, i) => (
            <tr key={i}>
              <td className={c.status === "met" ? "pass" : c.status === "missing" ? "fail" : ""}>{c.status}</td>
              <td>{c.requirement}</td>
              <td className="muted">{c.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Before you submit</h3>
      <List items={pkg.owner_todo as string[]} />

      <h3>AI-use disclosure</h3>
      {sub.status === "ready" ? (
        <form action={saveSubmission} className="stack">
          <Hidden name="id" value={sub.id} />
          <Hidden name="event_id" value={id} />
          <textarea name="disclosure" defaultValue={sub.disclosure} minLength={20} maxLength={8000} />
          <div className="actions"><button type="submit">Save disclosure</button></div>
        </form>
      ) : (
        <Prose text={sub.disclosure} />
      )}

      {status === "submission_ready" && sub.status === "ready" && (
        <form action={decide} className="stack">
          <h3>Gate 4 · Submission</h3>
          <p className="callout">
            The system never submits. Submit on the event platform yourself, then confirm here.
          </p>
          <Hidden name="event_id" value={id} />
          <Hidden name="gate" value="submission" />
          <label>
            Notes (required to send back for changes)
            <textarea name="reason" maxLength={4000} />
          </label>
          <label className="inline">
            <input type="checkbox" name="confirm_submitted" value="on" />
            I submitted this entry on the platform myself
          </label>
          <div className="actions">
            <button className="primary" name="decision" value="approve">Confirm submitted</button>
            <button name="decision" value="revise">Request changes</button>
            <button className="danger" name="decision" value="reject">Withdraw</button>
          </div>
        </form>
      )}
      {sub.submitted_at && <p className="pass">Submitted {fmtDate(sub.submitted_at, true)}.</p>}
    </Section>
  );
}
