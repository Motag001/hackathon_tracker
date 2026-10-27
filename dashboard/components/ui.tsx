import type { ReactNode } from "react";

const STATUS_TONE: Record<string, string> = {
  awaiting_approval: "warn",
  plan_ready: "warn",
  awaiting_input: "warn",
  submission_ready: "warn",
  paused_budget: "danger",
  rejected: "muted",
  filtered_out: "muted",
  below_threshold: "muted",
  duplicate: "muted",
  submitted: "ok",
  results_in: "ok",
  closed: "muted",
};

export function Status({ value }: { value: string }) {
  return <span className={`badge ${STATUS_TONE[value] ?? "info"}`}>{value.replaceAll("_", " ")}</span>;
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  );
}


export function Flash({ error, ok }: { error?: string; ok?: string }) {
  if (error) {
    return <p className="flash error" role="alert">{error}</p>;
  }
  if (ok) return <p className="flash ok" role="status">Saved.</p>;
  return null;
}

/** Model- or web-sourced text: always rendered as plain text, never as HTML. */
export function Prose({ text }: { text?: string | null }) {
  if (!text) return <p className="muted">—</p>;
  return <div className="prose">{text}</div>;
}

export function List({ items, empty = "None" }: { items?: (string | null | undefined)[] | null; empty?: string }) {
  const clean = (items ?? []).filter((x): x is string => !!x);
  if (!clean.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="list">
      {clean.map((x, i) => (
        <li key={i}>{x}</li>
      ))}
    </ul>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
