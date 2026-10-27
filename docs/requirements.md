# Hackathon Agent System: Requirements Document

Version 0.1 (draft for review). No code is written until this document is approved.

---

## 1. Purpose

A single-user, multi-agent system that finds realistic, winnable online hackathons, proposes them for your approval, plans and builds the project with you in the loop, prepares a submission package, and waits for you to review and click submit yourself. It learns from past results through a "What I learned" record and a performance log.

### Principles

1. **You make the decisions that matter.** The agent proposes. You approve the event, the plan, any input it needs from you, and the final submission.
2. **Honest authorship.** Every submission includes an AI-use disclosure, drafted per event and reviewed by you. The system is not designed to hide AI involvement from organizers or judges.
3. **Rules first.** Each event's rules are parsed and checked before any planning. Events that forbid something the plan requires are rejected.
4. **Cost discipline.** Total Anthropic spend is capped at $10/month. Routine work uses the cheapest suitable model.
5. **Realistic selection.** Most hackathons are not worth entering. The agent should reject more than it accepts.

---

## 2. Scope

### In scope (v1)
- Discovery from Devpost, MLH, and Devfolio
- Scoring and selection of events
- Rules parsing and risk flagging
- Plan generation with approval gates
- Build assistance with a skill registry (documents, slides, spreadsheets, PDFs, code, design, and so on)
- Submission package generation (text, files, demo script, disclosure)
- In-site notifications and dashboard
- Performance log and "What I learned" records
- Single-user login

### Out of scope (v1)
- Telegram, email, or SMS notifications
- Team formation and team entries (solo only for now)
- In-person events
- Any automatic submission, payment, account creation, or sign-up without your click
- Hiding AI involvement from organizers, judges, or participants
- Multi-user accounts

---

## 3. Users and Roles

- **Owner (you):** the only user. Logs in to the dashboard, approves events, reviews plans and submissions, clicks submit, and writes or edits "What I learned" entries.
- **Agents:** software components acting on your behalf within approved boundaries. They can read, draft, compute, and build in a sandbox. They cannot submit, pay, sign up for events, or accept terms without your approval.

---

## 4. Agent Roles

| Agent | Responsibility | Default model tier |
|---|---|---|
| Discovery | Pulls listings from Devpost, MLH, Devfolio; deduplicates; stores raw events | Scripted (no LLM) where possible; cheap model for classification |
| Rules Analyst | Reads each event's rules, extracts requirements, eligibility, AI-use policy, deadlines, judging criteria; flags risks | Cheap model |
| Scout (Scorer) | Scores events against the selection model (section 6) and produces a recommendation with reasons | Cheap model for scoring, mid-tier for borderline cases |
| Planner | Drafts a milestone plan: ideation, scope, build, demo, submission; selects skills and datasets | Mid-tier model |
| Builder | Produces code, documents, slides, datasets, and tests inside the workspace; logs each skill used | Mid-tier model; top-tier only for hard technical steps with approval |
| Reviewer | Checks the submission against the rules checklist and judging criteria; drafts the disclosure | Mid-tier model |
| Analyst | Updates the performance log and drafts "What I learned" from results, feedback, and time logs | Cheap model |

Agents communicate through the database (records and status), not through free-form chat between them. Each agent writes its output to a table, and the next agent reads from there.

---

## 5. Workflow and Approval Gates

```
Discover → Rules Analysis → Score → [GATE 1: Event approval]
  → Plan Draft → [GATE 2: Plan approval]
  → Inputs requested from you (as needed) → [GATE 3: Inputs provided]
  → Build (milestones) → Review → [GATE 4: Submission review]
  → You submit manually → Results & feedback → Analyst → "What I learned"
```

### Gate definitions

**GATE 1 (Event approval).** The dashboard shows candidate events above the threshold, with score breakdown, rules summary, deadline, time estimate, and risks. You approve, reject, or defer. Rejection reasons are recorded and fed back into scoring.

**GATE 2 (Plan approval).** The plan lists milestones with estimated hours, required skills, datasets, inputs needed from you, the proposed problem and angle, and the AI-use disclosure draft. You approve, edit, or send back for revision.

**GATE 3 (Inputs).** When the build needs something only you can provide (a credential, a dataset you own, a decision about scope, a personal anecdote, access to an account), the agent creates an input request with a clear description. Work on dependent milestones pauses until you respond.

**GATE 4 (Submission review).** The agent prepares a submission package: project name, description, video or demo script, repository or files, screenshots, required form fields, and the disclosure. You review, edit, and then submit manually on the event's platform. The agent never submits.

### Notifications (in-site only)
- Dashboard alert badge and an "Action needed" inbox
- Alert types: new event awaiting approval, plan ready, input needed, submission ready for review, event deadline within 48 hours, weekly summary
- Alerts can be marked read or snoozed. No external messaging.

---

## 6. Event Selection Model

### Hard filters (reject if any fail)
- Online only
- Not fully free (any prize, cash, credit, or reward at or above the minimum counts)
- Cash-equivalent prize value at or above **$50** (credits and product licenses are valued at their stated cash-equivalent, or marked as unknown and scored lower)
- Total effort at or below **72 hours** (including the agent's estimate of your time; estimates are checked against past actuals)
- Solo entry allowed
- No rule that prohibits AI-assisted work outright
- No rule that requires something the plan cannot deliver (for example, a hardware kit, a specific cloud account you don't have, or a proprietary dataset you can't access)
- Registration and submission still open with enough time for the plan

### Scored factors (0–100 weighted)

| Factor | Weight | What it measures |
|---|---|---|
| Prize value per estimated hour | 25 | Expected value compared to your time |
| Fit | 20 | Overlap with your skills, tools, and interests |
| Competition | 20 | Registrant count, track size, sponsor depth; smaller, well-matched fields score higher |
| Rule risk | 15 | Clarity of rules; AI-use policy; eligibility; submission format |
| Judging alignment | 10 | How well the criteria match what the agents can produce well |
| Past performance | 10 | Your results on similar formats and themes |

Events scoring below a threshold (default 65) are logged but not sent to you. The threshold is adjustable on the dashboard.

### Rejection logging
Every rejected event records the reason. Patterns are reviewed in the monthly summary so the scoring improves over time.

---

## 7. Skills and Tools

### Skill registry
The Builder and Planner select from a registry of available skills. Each skill entry records:
- Name and purpose
- Required inputs and outputs
- Any cost or rate considerations
- Usage count and success rate across events

Available skills at launch include document creation (Word, PDF), slide decks, spreadsheets, code generation and testing, and design or diagram generation. The registry expands as you add skills.

### Datasets
Datasets are chosen per event and logged. Sources:
- Public: Hugging Face Datasets, Kaggle, UCI Machine Learning Repository
- Nigeria and African context: National Bureau of Statistics (Nigeria), World Bank Open Data, Our World in Data
- Your own data, only with your explicit approval per event

Each dataset entry records its license. The agent checks the license against the event's rules before use.

### Local context
Where the event topic allows, the plan includes real local context: Nigerian and West African examples, data from local sources, and problems you have personally observed or verified. Claims about local conditions must be sourced. The agent does not invent statistics, testimonials, or anecdotes. Anecdotes come from you.

---

## 8. Disclosure and Integrity

- Every submission includes an **AI-use disclosure** that describes which tools were used, for which parts, and who made the final decisions. The agent drafts it; you review and edit it.
- The Reviewer checks the disclosure against the event's AI-use rules before GATE 4.
- If an event requires disclosure in a specific format, the disclosure follows that format.
- The system does not generate content designed to conceal AI involvement, impersonate other people, or fabricate testimonials, results, or user data.

---

## 9. Performance Analytics and Learning

### Records kept per event
- Event metadata, score breakdown, and your decision (approve, reject, defer, and why)
- Plan versus actual hours, by milestone
- Skills and datasets used
- Anthropic token spend and cost
- Submission status and date
- Results: placement, prize won (if any), judge feedback, and any notes from the platform
- **"What I learned"** section with three parts: what went well, what I would change, and what I'd carry forward. Drafted by the Analyst; edited and approved by you.

### Use by agents
The Scout, Planner, and Analyst read the performance log before scoring or planning. Summaries are kept compact so that reading them does not consume much of the token budget. Recurring lessons are promoted to a short "playbook" that the Planner reads for each new event.

### Metrics on the dashboard
- Events considered, approved, submitted, and placed
- Win rate and average placement by event type
- Hours invested versus prize money earned
- Cost per submission (Anthropic spend)
- Estimate accuracy (planned versus actual hours)

---

## 10. Cost Controls ($10/month cap)

### Limits
- Hard monthly cap of **$10** set in the Anthropic Console
- Internal soft warnings at **$5** (informational) and **$8** (agents pause all non-essential work until the next cycle)
- Per-event token budget (default: $1.50 per event build), shown on the event page
- Dashboard displays month-to-date spend and projected month-end spend

### Model routing (default)
- Scanning, classification, and scoring: smallest suitable model
- Rules parsing and summarizing feedback: smallest suitable model, with caching
- Planning, building, and review: mid-tier model
- Top-tier model: only for a specific, approved, hard step, and logged

### Efficiency measures
- Prompt caching for stable context (your profile, playbook, skill registry, event rules)
- Batch processing for non-urgent work (discovery and scoring)
- Stored intermediate results so the same rules page isn't re-read
- Stop conditions: if an event's build exceeds its token budget, the agent pauses and asks you whether to continue

---

## 11. Architecture

### Components and hosting

| Component | Platform | Purpose |
|---|---|---|
| Scheduled jobs (discovery, scoring, agent runs) | GitHub Actions (scheduled workflows) | Runs Python agents on a schedule and on demand |
| Dashboard | Vercel (Hobby tier) | Next.js or Python-served UI for approvals, alerts, plans, and logs |
| Database, auth, storage | Supabase (free tier) | Tables, single-user login, file storage for packages |
| Source and workflows | GitHub (private repo) | Code, workflows, and skill definitions |
| LLM | Anthropic API | Agent reasoning and drafting |

### Important constraints
- **GitHub Actions timing:** scheduled runs have a minimum interval of five minutes and can be delayed under load. The system is designed for hourly or daily discovery, not real-time.
- **Supabase free tier:** projects pause after a period of inactivity. A scheduled keep-alive job runs in GitHub Actions to prevent this.
- **Vercel and long jobs:** Vercel serves the dashboard and handles light requests only. Agent work runs in GitHub Actions, not on Vercel.
- **Secrets:** Anthropic and Supabase keys are stored in GitHub Actions secrets and Vercel environment variables, never in the repository.

### Repository structure (proposed)

```
hackagent/
├── agents/            # discovery, rules, scout, planner, builder, reviewer, analyst
├── skills/            # skill registry and definitions
├── pipelines/         # workflow orchestration
├── sources/           # Devpost, MLH, Devfolio adapters
├── shared/            # models, prompts, cost tracking, utilities
├── tests/
├── .github/workflows/ # scheduled jobs, keep-alive
├── dashboard/         # Vercel app
└── docs/              # this document, decisions log
```

---

## 12. Data Model (Supabase)

Core tables (names provisional):

- **users**: single owner record, linked to Supabase Auth
- **sources**: platform definitions and adapter status
- **events**: normalized listings (platform, title, URL, dates, prize, cash-equivalent value, eligibility, online flag, themes, status)
- **event_rules**: parsed rules (requirements, AI-use policy, team rules, submission format, judging criteria, risks) with source snapshot and timestamp
- **scores**: score per factor, total, model version, reason text
- **decisions**: your approval, rejection, or defer, with reason
- **plans**: milestones, hour estimates, skills, datasets, inputs needed, status
- **milestones**: per-plan tasks with status and actual hours
- **input_requests**: what the agent needs from you, status, response
- **artifacts**: files and outputs produced, with storage path and skill used
- **skills**: registry entries with usage and success statistics
- **submissions**: package contents, disclosure text, review notes, final status (you submit manually; the system records the date you confirm)
- **results**: placement, prize, judge feedback
- **learnings**: "What I learned" entries (went well, change, carry forward), drafted and approved
- **playbook**: distilled lessons read by agents
- **alerts**: in-site notifications with read or snooze state
- **spend_log**: per-run token usage and cost

Row-level security restricts all tables to the owner account.

---

## 13. Security and Privacy

- Single-user Supabase Auth with email login and strong password; multi-factor authentication recommended
- Row-level security on every table
- No credentials for hackathon platforms are stored by the agents. You log in to platforms yourself.
- The agent never enters payment details, passwords, or personal identity documents
- Personal information in submissions is limited to what the event requires, and you review it before submitting
- Artifacts are private by default; sharing requires you to act

---

## 14. Phases and Milestones

**Phase 0: Foundations (week 1)**
- Create GitHub, Vercel, Supabase, and Anthropic accounts; set the $10 cap
- Repository, Python environment, secrets, and CI
- Database schema and migrations
- Cost tracker wired to every model call

**Phase 1: Discovery and scoring (weeks 2–3)**
- Devpost, MLH, and Devfolio adapters, with terms checked per source
- Normalization, deduplication, and storage
- Rules Analyst and Scout
- Dashboard: event list with score breakdown and approve, reject, defer

**Phase 2: Planning and approvals (weeks 4–5)**
- Planner with skill registry and dataset selection
- Plan review screen and GATE 2
- Input requests and GATE 3
- Alerts inbox

**Phase 3: Build and review (weeks 6–8)**
- Builder with milestone execution, skill logging, and artifact storage
- Reviewer and disclosure drafting
- Submission package and GATE 4
- Token budget enforcement and pause behavior

**Phase 4: Learning and analytics (weeks 9–10)**
- Results entry and feedback capture
- Analyst, "What I learned" drafts, and playbook updates
- Performance dashboard and scoring model updates

**Phase 5: Hardening (ongoing)**
- Test runs on past hackathons
- Cost review at the end of each month
- Source and terms review every quarter

Timelines assume part-time work and will be adjusted after Phase 0.

---

## 15. Success Criteria

- The system surfaces at least a few realistic events per month that meet all hard filters
- Every approved event has a plan with hour estimates within a reasonable margin of actual time
- No submission leaves the system without your click
- Monthly Anthropic spend stays at or under $10
- Each submission includes a reviewed, honest disclosure
- Every entered event produces a "What I learned" record
- Win rate and estimate accuracy trend upward over three months of data

---

## 16. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Source sites change layout or restrict access | Adapter per source; failure alerts; prefer official feeds; check terms before each source is enabled |
| Events have unclear or changing rules | Rules Analyst flags ambiguity; you decide before planning |
| Cost overrun | Caps, soft warnings, per-event budgets, model routing, caching |
| Low win rate and time loss | Strict scoring, rejection learning, hour estimates tracked against actuals |
| Disqualification over AI use | Mandatory disclosure, Reviewer check, rule-based rejection |
| Scheduled jobs delayed | Designed for daily or hourly polling; deadline alerts are set with buffer time |
| Supabase pausing | Keep-alive workflow |
| Over-reliance on agents | Human gates at four points; you write "What I learned" yourself, with agent drafts as a starting point |

---

## 17. Open Items (to confirm before build)

1. Threshold for surfacing events (default 65), or do you want a different number?
2. Default per-event build budget ($1.50), or a different figure?
3. Your skill profile: languages beyond Python, cloud accounts, and any datasets you can access. Please list them.
4. Your primary interests in AI/ML, to set the initial fit scoring (even though the agents should not be restricted to a single area).
5. Preferred dashboard framework: Next.js (TypeScript) or a Python-served UI. Python is your go-to, but Next.js is the standard choice for Vercel.
6. Whether submission packages should be stored in Supabase Storage or in a private GitHub repository.

---

## 18. Decision Log

| Date | Decision | Source |
|---|---|---|
| 2026-10-27 | Sources: Devpost, MLH, Devfolio | Owner |
| 2026-10-27 | Online only; not fully free; minimum $50 prize; maximum 72 hours | Owner |
| 2026-10-27 | Solo entries for now | Owner |
| 2026-10-27 | Notifications in-site only; no Telegram | Owner |
| 2026-10-27 | Single-user login | Owner |
| 2026-10-27 | Hosting: GitHub Actions, Vercel, Supabase | Owner |
| 2026-10-27 | Anthropic budget: $10/month cap | Owner |
| 2026-10-27 | Agent never submits; owner submits manually | Owner |
| 2026-10-27 | AI-use disclosure required on every submission | Assistant recommendation, accepted |
