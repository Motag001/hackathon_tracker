"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { requireOwner } from "@/lib/auth";
import { supabaseServer } from "@/lib/supabase";

// Server actions: each one re-checks the owner session, validates its input
// with zod, and leaves authorisation of the write to RLS and the database
// gate triggers. Errors are passed back as a short message in the URL.

const uuid = z.string().uuid();
const text = (max: number) => z.string().trim().max(max);
/** Blank form fields mean "not provided", never zero. */
const blank = (v: unknown) => (v === "" || v === null ? undefined : v);
const optionalNumber = (min: number, max: number, int = false) =>
  z.preprocess(blank, (int ? z.coerce.number().int() : z.coerce.number()).min(min).max(max).optional());

function back(path: string, error?: string): never {
  const sep = path.includes("?") ? "&" : "?";
  redirect(error ? `${path}${sep}error=${encodeURIComponent(error.slice(0, 300))}` : path);
}

function parse<T extends z.ZodTypeAny>(schema: T, form: FormData, path: string): z.infer<T> {
  const result = schema.safeParse(Object.fromEntries(form));
  if (!result.success) back(path, result.error.issues.map((i) => i.message).join("; "));
  return result.data;
}

// --- auth -----------------------------------------------------------------

export async function signIn(form: FormData) {
  const input = z
    .object({ email: z.string().email().max(320), password: z.string().min(1).max(200) })
    .safeParse(Object.fromEntries(form));
  if (!input.success) back("/login", "Enter your email and password.");
  const supabase = await supabaseServer();
  const { error } = await supabase.auth.signInWithPassword(input.data);
  // One generic message: do not reveal whether the account exists.
  if (error) back("/login", "Sign-in failed.");
  redirect("/");
}

export async function verifyMfa(form: FormData) {
  const input = z.object({ code: z.string().regex(/^\d{6}$/) }).safeParse(Object.fromEntries(form));
  if (!input.success) back("/mfa", "Enter the 6-digit code.");
  const supabase = await supabaseServer();
  const { data: factors } = await supabase.auth.mfa.listFactors();
  const totp = factors?.totp?.find((f) => f.status === "verified");
  if (!totp) back("/mfa", "No verified authenticator found.");
  const { error } = await supabase.auth.mfa.challengeAndVerify({
    factorId: totp.id,
    code: input.data.code,
  });
  if (error) back("/mfa", "Code not accepted.");
  redirect("/");
}

export async function signOut() {
  const supabase = await supabaseServer();
  await supabase.auth.signOut();
  redirect("/login");
}

const MFA_COOKIE = "mfa_enroll";

export async function enrollMfa() {
  const { supabase } = await requireOwner();
  // Clear abandoned attempts so only one unverified factor exists.
  const { data: factors } = await supabase.auth.mfa.listFactors();
  for (const f of factors?.all ?? []) {
    if (f.factor_type === "totp" && f.status === "unverified") {
      await supabase.auth.mfa.unenroll({ factorId: f.id });
    }
  }
  const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp" });
  if (error || !data) back("/settings", "Could not start MFA enrolment.");
  // The QR code and secret are only returned now; keep them for ten minutes
  // in an httpOnly cookie scoped to the enrolment page.
  (await cookies()).set(
    MFA_COOKIE,
    JSON.stringify({ id: data.id, qr: data.totp.qr_code, secret: data.totp.secret }),
    { httpOnly: true, secure: true, sameSite: "strict", path: "/settings/mfa", maxAge: 600 },
  );
  redirect("/settings/mfa");
}

export async function confirmMfa(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({ factor: z.string().min(1).max(100), code: z.string().regex(/^\d{6}$/) }),
    form,
    "/settings",
  );
  const { error } = await supabase.auth.mfa.challengeAndVerify({
    factorId: input.factor,
    code: input.code,
  });
  if (error) back("/settings/mfa", "Code not accepted.");
  (await cookies()).delete({ name: MFA_COOKIE, path: "/settings/mfa" });
  back("/settings?ok=mfa");
}

// --- gates ------------------------------------------------------------------

const decisionSchema = z.object({
  event_id: uuid,
  gate: z.enum(["event", "plan", "submission"]),
  decision: z.enum(["approve", "reject", "defer", "revise"]),
  plan_id: z.preprocess(blank, uuid.optional()),
  reason: text(4000).optional(),
  confirm_submitted: z.literal("on").optional(),
});

/** Every gate goes through the append-only decisions table. */
export async function decide(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(decisionSchema, form, path);
  if (input.decision === "reject" && !input.reason) back(path, "Give a reason for rejecting.");
  if (input.decision === "revise" && !input.reason) back(path, "Say what should change.");
  if (input.gate === "submission" && input.decision === "approve" && !input.confirm_submitted) {
    back(path, "Tick the box to confirm you submitted on the platform yourself.");
  }
  const { error } = await supabase.from("decisions").insert({
    event_id: input.event_id,
    gate: input.gate,
    decision: input.decision,
    plan_id: input.plan_id ?? null,
    reason: input.reason || null,
  });
  if (error) back(path, error.message);
  revalidatePath("/", "layout");
  back(path);
}

export async function answerInput(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(
    z.object({
      id: uuid,
      event_id: uuid,
      action: z.enum(["answer", "decline"]),
      response: text(10000).optional(),
    }),
    form,
    path,
  );
  const response = input.response ?? "";
  // Defence in depth: refuse things that look like secrets. Credentials are
  // configured by the owner directly in GitHub/Vercel, never stored here.
  if (/sk-ant-|eyJ[\w-]{10,}\.[\w-]{10,}\.|-----BEGIN|password\s*[:=]/i.test(response)) {
    back(path, "That looks like a secret. Configure credentials yourself; never paste them here.");
  }
  if (input.action === "answer" && !response) back(path, "Write a response or decline.");
  const { error } = await supabase
    .from("input_requests")
    .update({
      status: input.action === "answer" ? "answered" : "declined",
      response: input.action === "answer" ? response : null,
    })
    .eq("id", input.id)
    .eq("status", "pending");
  if (error) back(path, error.message);
  revalidatePath("/", "layout");
  back(path);
}

export async function updateMilestone(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(
    z.object({
      id: uuid,
      event_id: uuid,
      status: z.enum(["done", "skipped", "pending", "drafted"]),
      actual_hours: optionalNumber(0, 500),
    }),
    form,
    path,
  );
  const patch: Record<string, unknown> = { status: input.status };
  if (input.actual_hours !== undefined) patch.actual_hours = input.actual_hours;
  const { error } = await supabase.from("milestones").update(patch).eq("id", input.id);
  if (error) back(path, error.message);
  back(path);
}

export async function saveSubmission(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(
    z.object({ id: uuid, event_id: uuid, disclosure: text(8000).min(20) }),
    form,
    path,
  );
  const { error } = await supabase
    .from("submissions")
    .update({ disclosure: input.disclosure })
    .eq("id", input.id)
    .eq("status", "ready");
  if (error) back(path, error.message);
  back(path);
}

export async function recordResult(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(
    z.object({
      event_id: uuid,
      placement: optionalNumber(1, 100000, true),
      placement_text: text(200).optional(),
      prize_won_usd: optionalNumber(0, 10_000_000),
      judge_feedback: text(20000).optional(),
      platform_notes: text(5000).optional(),
    }),
    form,
    path,
  );
  const { error } = await supabase.from("results").upsert(
    {
      event_id: input.event_id,
      placement: input.placement ?? null,
      placement_text: input.placement_text || null,
      prize_won_usd: input.prize_won_usd ?? 0,
      judge_feedback: input.judge_feedback || null,
      platform_notes: input.platform_notes || null,
    },
    { onConflict: "event_id" },
  );
  if (error) back(path, error.message);
  back(path);
}

export async function saveLearning(form: FormData) {
  const { supabase } = await requireOwner();
  const path = `/events/${form.get("event_id")}`;
  const input = parse(
    z.object({
      event_id: uuid,
      went_well: text(5000),
      would_change: text(5000),
      carry_forward: text(5000),
      approve: z.enum(["yes", "no"]).default("no"),
    }),
    form,
    path,
  );
  const { error } = await supabase.from("learnings").upsert(
    {
      event_id: input.event_id,
      went_well: input.went_well,
      would_change: input.would_change,
      carry_forward: input.carry_forward,
      status: input.approve === "yes" ? "approved" : "draft",
    },
    { onConflict: "event_id" },
  );
  if (error) back(path, error.message);
  back(path);
}

// --- alerts, playbook, settings --------------------------------------------

export async function updateAlert(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({ id: uuid, action: z.enum(["read", "snooze"]) }),
    form,
    "/",
  );
  const patch =
    input.action === "read"
      ? { read_at: new Date().toISOString() }
      : { snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString() };
  const { error } = await supabase.from("alerts").update(patch).eq("id", input.id);
  if (error) back("/", error.message);
  revalidatePath("/", "layout");
  back("/");
}

export async function updatePlaybook(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({ id: uuid, status: z.enum(["active", "retired", "proposed"]) }),
    form,
    "/playbook",
  );
  const { error } = await supabase.from("playbook").update({ status: input.status }).eq("id", input.id);
  if (error) back("/playbook", error.message);
  back("/playbook");
}

export async function addPlaybook(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(z.object({ lesson: text(500).min(5) }), form, "/playbook");
  const { error } = await supabase.from("playbook").insert({ lesson: input.lesson, status: "active" });
  if (error) back("/playbook", error.message);
  back("/playbook");
}

const profileSchema = z
  .object({
    country: z.string().max(80).optional(),
    hours_per_day: z.number().min(0.5).max(16).optional(),
    skills: z.array(z.string().max(80)).max(100).optional(),
    languages: z.array(z.string().max(80)).max(50).optional(),
    tools: z.array(z.string().max(80)).max(100).optional(),
    cloud_accounts: z.array(z.string().max(80)).max(50).optional(),
    hardware: z.array(z.string().max(80)).max(50).optional(),
    datasets: z.array(z.string().max(200)).max(50).optional(),
    interests: z.array(z.string().max(80)).max(50).optional(),
    notes: z.string().max(2000).optional(),
  })
  .strict();

export async function saveSettings(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({
      surface_threshold: z.coerce.number().min(0).max(100),
      event_budget_usd: z.coerce.number().gt(0).max(10),
      min_prize_usd: z.coerce.number().min(0).max(1_000_000),
      max_effort_hours: z.coerce.number().gt(0).max(500),
      profile: z.string().max(20000),
    }),
    form,
    "/settings",
  );
  let profile: unknown;
  try {
    profile = JSON.parse(input.profile || "{}");
  } catch {
    back("/settings", "Profile must be valid JSON.");
  }
  const checked = profileSchema.safeParse(profile);
  if (!checked.success) back("/settings", `Profile: ${checked.error.issues[0]?.message ?? "invalid"}`);
  const { error } = await supabase
    .from("settings")
    .update({
      surface_threshold: input.surface_threshold,
      event_budget_usd: input.event_budget_usd,
      min_prize_usd: input.min_prize_usd,
      max_effort_hours: input.max_effort_hours,
      profile: checked.data,
    })
    .eq("id", 1);
  if (error) back("/settings", error.message);
  back("/settings?ok=saved");
}

export async function updateSource(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({
      id: z.enum(["devpost", "mlh", "devfolio"]),
      enabled: z.enum(["true", "false"]),
      terms_reviewed: z.enum(["on"]).optional(),
      terms_notes: text(2000).optional(),
    }),
    form,
    "/settings",
  );
  const enable = input.enabled === "true";
  if (enable && !input.terms_reviewed) {
    back("/settings", "Confirm you reviewed the site's terms before enabling it.");
  }
  const patch: Record<string, unknown> = { enabled: enable, terms_notes: input.terms_notes || null };
  if (input.terms_reviewed) patch.terms_reviewed_at = new Date().toISOString();
  const { error } = await supabase.from("sources").update(patch).eq("id", input.id);
  if (error) back("/settings", error.message);
  back("/settings?ok=saved");
}

export async function toggleSkill(form: FormData) {
  const { supabase } = await requireOwner();
  const input = parse(
    z.object({ id: z.string().regex(/^[a-z_]{1,40}$/), enabled: z.enum(["true", "false"]) }),
    form,
    "/settings",
  );
  const { error } = await supabase
    .from("skills")
    .update({ enabled: input.enabled === "true" })
    .eq("id", input.id);
  if (error) back("/settings", error.message);
  back("/settings?ok=saved");
}
