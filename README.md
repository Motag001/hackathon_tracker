# Hackathon Agent System

A single-user, human-in-the-loop multi-agent system that finds realistic online
hackathons, proposes them for approval, plans and drafts the project with you,
prepares a submission package, and waits for **you** to submit. Requirements:
[`docs/requirements.md`](docs/requirements.md). Decisions:
[`docs/decisions.md`](docs/decisions.md).

```
Discover → Rules → Score → [GATE 1 event] → Plan → [GATE 2 plan] → [GATE 3 inputs]
  → Build → Review → [GATE 4 you submit manually] → Results → Analyst → "What I learned"
```

## Layout

| Path | What |
|---|---|
| `hackagent/sources/` | Devpost, MLH and Devfolio adapters (off until you review each site's terms) |
| `hackagent/agents/` | `discovery`, `rules_analyst`, `scout`, `planner`, `builder`, `reviewer`, `analyst`, `notifier` |
| `hackagent/shared/` | config, data store, LLM gateway, budget guard, security helpers, history |
| `hackagent/skills/` | skill registry (`registry.json`) and local renderers (docx, pdf, pptx, xlsx) |
| `hackagent/sandbox/` | runner for model-generated tests (no-secrets CI job) and result recorder |
| `hackagent/pipelines/cli.py` | `hackagent <command>` entry point used by the workflows |
| `supabase/migrations/` | schema, RLS, gate triggers, views |
| `supabase/tests/` | gate and RLS tests run against plain Postgres in CI |
| `dashboard/` | Next.js dashboard for Vercel (approvals, inbox, spend, performance, settings) |
| `.github/workflows/` | CI, daily intake, 3-hourly agent cycle, Supabase keep-alive |

## How the agents work

* **Discovery** (no model): reads enabled sources, normalises, de-duplicates
  across platforms, and drops obvious misses (in-person, invite-only, closing
  within 48h, prize below the minimum) before any tokens are spent.
* **Rules Analyst** (cheap model): fetches rules pages through an allowlisted,
  HTTPS-only fetcher, hashes the text and skips the model when nothing changed.
  Four or more events go through the Batches API at half price.
* **Scout** (cheap model, mid for borderline): hard filters and five of six
  weighted factors are deterministic; the model only judges fit, judging
  alignment, effort and unmet requirements. Effort estimates are calibrated
  against your recorded actual hours. Your rejection reasons and the playbook
  are fed back in.
* **Planner** (mid model): milestones, skills, datasets, inputs and a disclosure
  draft, then deterministic checks (registry-only skills, dataset licenses, hour
  limit, AI disclosure present).
* **Builder** (mid model; top tier only after you answer "yes"): writes files for
  one milestone at a time, waits on pending inputs, validates every path and
  type, renders documents locally, stores files in a private bucket.
* **Reviewer** (mid model): checklist against rules and judging criteria, final
  disclosure, integrity check, submission package. Problems are shown as
  blocking issues on the dashboard.
* **Analyst** (cheap model): drafts "What I learned" and proposes playbook
  lessons. You edit and approve both.
* **Notifier** (no model): 48-hour deadline alerts, weekly and monthly summaries
  with rejection patterns.

Agents communicate only through database records and statuses.

## Security model

* **Gates are enforced in the database, not just the UI.** Agents use the
  service-role key, which bypasses RLS, so every gate is a trigger the service
  role cannot bypass: decisions, plan approval, input answers, results,
  learning approval, playbook activation and submission confirmation all
  require `auth.uid()` to be the owner. Decisions are append-only. See
  `supabase/tests/test_gates.sql`.
* **Single user.** A singleton `app_owner` table; RLS on every table restricts
  reads and writes to that user. Disable sign-ups in Supabase.
* **No sign-in (owner's choice).** The dashboard has no login, password or
  session. On the server it mints a 5-minute Supabase token for
  `OWNER_USER_ID`, signed with `SUPABASE_JWT_SECRET` (server-only Vercel
  variables, never sent to the browser). RLS and the gate triggers work
  unchanged, so the agents still cannot approve anything, but **anyone who can
  reach the deployment can act as the owner**. Keep the URL private, or turn on
  Vercel Deployment Protection to put a Vercel login in front of it.
* **Dashboard holds no service-role key.** Every server action validates its
  input with zod and writes through RLS as the owner. A
  per-request nonce CSP, HSTS, `frame-ancestors 'none'`, no-referrer and
  `no-store` caching are set. Model and web text is always rendered as plain
  text. Artifacts are downloaded through 60-second signed URLs.
* **Untrusted content.** Rules pages, judge feedback and generated files are
  wrapped as untrusted data in prompts, outputs are schema-constrained, and
  agents have no tools, so prompt injection can at most skew a draft that you
  review. Suspected injections are reported as rule risks.
* **Fetching.** HTTPS only, host allowlist, private and link-local addresses
  blocked (including after redirects), 2 MB cap, per-host rate limit.
* **Generated code never runs next to secrets.** Python files are staged and
  tested in a separate Actions job with no secrets and `permissions: {}`; the
  report is validated as untrusted input before it is recorded. Secret-holding
  jobs do not use the Actions cache. Spreadsheet output is protected against
  formula injection.
* **No credentials for platforms are stored.** Input requests reject anything
  that looks like a key, token or password; credentials are configured by you.
* **Secrets** live in GitHub Actions secrets (environment `agents`) and Vercel
  environment variables, never in the repository. Logs are redacted.

## Cost controls

Every model call goes through `shared/llm.py`, which prices the worst case
(full `max_tokens`) before sending and records real usage in `spend_log`.

| Line | Effect |
|---|---|
| $5 | informational alert |
| $8 | discovery, rules and scoring pause until next month |
| $10 | nothing runs (also set this cap in the Anthropic Console) |
| $1.50 per event | the event pauses and asks you; reply `yes` or an amount to extend |

Also: prompt caching for stable context, batch API for intake, content-hash
caching of rules, deterministic scoring where possible, model routing (Haiku
for intake/analysis, Sonnet for plan/build/review, Opus only with approval).

## Setup

1. **Supabase** (free tier): create a project. In *Authentication → Providers →
   Email*, disable sign-ups after creating your user, and require a strong
   password. Run `supabase/migrations/0001_init.sql` in the SQL editor (or
   `supabase db push`). Then register yourself as the owner:
   ```sql
   insert into public.app_owner (user_id)
   select id from auth.users where email = 'you@example.com';
   ```
2. **Anthropic**: create an API key and set a **$10 monthly limit** in the Console.
3. **GitHub** (private repo): create an environment named `agents` and add
   secrets `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
   Run the *Agents* workflow once with command `sync-skills`.
4. **Vercel** (Hobby): import the repo with root directory `dashboard`, and set
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `OWNER_USER_ID`
   (your user's UID from *Authentication → Users*) and `SUPABASE_JWT_SECRET`
   (*Settings → API → JWT Settings*), the last two as type *Sensitive*. Never the
   service-role key.
5. **Dashboard**: open it (there is no sign-in; `/status` explains any setup
   problem), fill in your profile, then read each source's terms and enable the
   ones you're comfortable with.

## Running locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,skills]"
pytest && ruff check . && mypy hackagent
HACKAGENT_DRY_RUN=true hackagent intake      # in-memory store, no model calls

# schema + gate tests against a throwaway Postgres
DATABASE_URL=postgresql://postgres@localhost/hack_test supabase/tests/run.sh

cd dashboard && npm ci && npm run typecheck && npm run dev
```

Commands: `intake`, `discover`, `rules`, `score`, `plan`, `build`, `review`,
`analyse`, `notify`, `cycle`, `sync-skills`, `record-tests <report>`, `keepalive`.

## Known limits

* Source adapters are built against each site's public listing format and are
  tested with fixtures. Layout changes raise a source-failure alert.
* Prize values in other currencies use approximate fixed rates; you confirm the
  value at Gate 1.
* GitHub's scheduler can delay runs; deadline alerts fire 48 hours ahead.
