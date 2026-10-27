import { addPlaybook, updatePlaybook } from "@/app/actions";
import { Flash, Section } from "@/components/ui";
import { requireOwner } from "@/lib/auth";
import { fmtDate } from "@/lib/format";

export default async function Playbook({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  const { supabase } = await requireOwner();
  const { data } = await supabase.from("playbook").select("*").order("created_at", { ascending: false });
  const rows = data ?? [];
  const by = (s: string) => rows.filter((r) => r.status === s);

  const Item = ({ r, actions }: { r: (typeof rows)[number]; actions: [string, string][] }) => (
    <li className="card">
      <div className="prose">{r.lesson}</div>
      <div className="actions">
        <span className="muted">{fmtDate(r.created_at)}</span>
        {actions.map(([status, label]) => (
          <form key={status} action={updatePlaybook}>
            <input type="hidden" name="id" value={r.id} />
            <input type="hidden" name="status" value={status} />
            <button type="submit">{label}</button>
          </form>
        ))}
      </div>
    </li>
  );

  return (
    <>
      <h1>Playbook</h1>
      <p className="muted">Active lessons are read by the Scout and Planner before every event.</p>
      <Flash error={error} />
      <Section title={`Proposed by the Analyst (${by("proposed").length})`}>
        <ul className="list">{by("proposed").map((r) => <Item key={r.id} r={r} actions={[["active", "Adopt"], ["retired", "Dismiss"]]} />)}</ul>
      </Section>
      <Section title={`Active (${by("active").length})`}>
        <ul className="list">{by("active").map((r) => <Item key={r.id} r={r} actions={[["retired", "Retire"]]} />)}</ul>
        <form action={addPlaybook} className="stack">
          <label>Add a lesson<textarea name="lesson" maxLength={500} required /></label>
          <div className="actions"><button className="primary" type="submit">Add</button></div>
        </form>
      </Section>
      <Section title={`Retired (${by("retired").length})`}>
        <ul className="list">{by("retired").map((r) => <Item key={r.id} r={r} actions={[["active", "Restore"]]} />)}</ul>
      </Section>
    </>
  );
}
