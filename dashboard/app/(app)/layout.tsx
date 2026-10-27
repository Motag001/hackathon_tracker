import Link from "next/link";
import type { ReactNode } from "react";

import { signOut } from "@/app/actions";
import { requireOwner } from "@/lib/auth";

export const dynamic = "force-dynamic";

const NAV = [
  ["/", "Inbox"],
  ["/events", "Events"],
  ["/active", "Active"],
  ["/spend", "Spend"],
  ["/performance", "Performance"],
  ["/playbook", "Playbook"],
  ["/settings", "Settings"],
] as const;

export default async function AppLayout({ children }: { children: ReactNode }) {
  const { supabase } = await requireOwner();
  const now = new Date().toISOString();
  const { count } = await supabase
    .from("alerts")
    .select("id", { count: "exact", head: true })
    .is("read_at", null)
    .or(`snoozed_until.is.null,snoozed_until.lt."${now}"`);

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <span className="brand">Hackathon Agent</span>
        {NAV.map(([href, label]) => (
          <Link key={href} href={href}>
            {label}
            {href === "/" && !!count && <span className="pill">{count}</span>}
          </Link>
        ))}
        <form action={signOut} className="nav-end">
          <button type="submit" className="link">Sign out</button>
        </form>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
