// Display helpers. The owner is in Lagos; times are shown in that zone.
const TZ = "Africa/Lagos";

export function fmtDate(value?: string | null, withTime = false): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-GB", {
    timeZone: TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function fmtUsd(value?: number | string | null, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits })
    : "—";
}

export function fmtNum(value?: number | string | null, digits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits).replace(/\.0+$/, "") : "—";
}

export function hoursUntil(value?: string | null): number | null {
  if (!value) return null;
  return (new Date(value).getTime() - Date.now()) / 3_600_000;
}

/** Only http(s) links are rendered as anchors; anything else is shown as text. */
export function safeHref(url?: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** CSS width class for a 0-1 ratio (inline styles are blocked by the CSP). */
export function widthClass(ratio: number): string {
  const pct = Math.max(0, Math.min(100, Math.round((ratio * 100) / 5) * 5));
  return `w-${pct}`;
}
