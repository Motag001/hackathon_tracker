# Decision log

Decisions from the requirements (section 18) plus those made during the build.
Items marked *default* resolve an open question from section 17 and can be
changed on the dashboard or in code.

| Date | Decision | Source |
|---|---|---|
| 2026-10-27 | Sources: Devpost, MLH, Devfolio | Owner |
| 2026-10-27 | Online only; not fully free; minimum $50 prize; maximum 72 hours | Owner |
| 2026-10-27 | Solo entries for now | Owner |
| 2026-10-27 | Notifications in-site only | Owner |
| 2026-10-27 | Single-user login | Owner |
| 2026-10-27 | Hosting: GitHub Actions, Vercel, Supabase | Owner |
| 2026-10-27 | Anthropic budget: $10/month cap | Owner |
| 2026-10-27 | Agent never submits; owner submits manually | Owner |
| 2026-10-27 | AI-use disclosure required on every submission | Accepted recommendation |
| 2026-10-27 | Surface threshold 65 (open item 1) | *Default*, Settings page |
| 2026-10-27 | Per-event budget $1.50 (open item 2) | *Default*, Settings page |
| 2026-10-27 | Skill profile and interests (open items 3-4) are a JSON profile on the Settings page, not code | Build |
| 2026-10-27 | Dashboard: Next.js (TypeScript) on Vercel (open item 5) | Build, Vercel standard |
| 2026-10-27 | Submission packages and artifacts in a private Supabase Storage bucket (open item 6) | Build |
| 2026-10-27 | Model tiers: cheap `claude-haiku-5-5`, mid `claude-sonnet-5-5`, top `claude-opus-5-5`; overridable by env var | Build |
| 2026-10-27 | Gates enforced by database triggers so the service-role key cannot approve on the owner's behalf | Build, security |
| 2026-10-27 | Generated code is tested only in a CI job without secrets | Build, security |
| 2026-10-27 | Sources disabled until the owner records a terms review | Build, requirement 16 |
| 2026-10-27 | Agent cycle every 3 hours, intake daily, keep-alive every 3 days (Actions minutes budget) | Build |
| 2026-10-27 | Dashboard dependencies pinned exactly; Next.js 16.4.2 chosen over 16.4.0 because of critical advisories (GHSA-2464-fhr4-w9xw and others) | Build, security |
