-- Hackathon Agent System: initial schema.
--
-- Security model
--   * The dashboard talks to Supabase with the anon key + the owner's session.
--     Row-level security restricts every table to the single owner account.
--   * Agents (GitHub Actions) use the service role key, which bypasses RLS.
--     Human approval gates are therefore enforced with triggers, which the
--     service role cannot bypass: a decision, a plan approval, an input
--     response, a learning approval or a submission confirmation is rejected
--     unless auth.uid() is the owner.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Owner and settings
-- ---------------------------------------------------------------------------

create table public.app_owner (
    user_id    uuid primary key references auth.users (id) on delete cascade,
    created_at timestamptz not null default now()
);
-- Single-user system: at most one owner row can ever exist.
create unique index app_owner_singleton on public.app_owner ((true));

create or replace function public.is_owner()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select auth.uid() is not null
       and exists (select 1 from public.app_owner where user_id = auth.uid());
$$;

create or replace function public.require_owner(action text)
returns void
language plpgsql
stable
security definer
set search_path = public
as $$
begin
    if not public.is_owner() then
        raise exception 'Only the owner can %', action
            using errcode = '42501';
    end if;
end;
$$;

create table public.settings (
    id                 smallint primary key default 1 check (id = 1),
    surface_threshold  numeric(5, 2) not null default 65 check (surface_threshold between 0 and 100),
    event_budget_usd   numeric(6, 2) not null default 1.50 check (event_budget_usd > 0 and event_budget_usd <= 10),
    monthly_cap_usd    numeric(6, 2) not null default 10 check (monthly_cap_usd > 0 and monthly_cap_usd <= 10),
    soft_warn_usd      numeric(6, 2) not null default 5,
    pause_usd          numeric(6, 2) not null default 8,
    min_prize_usd      numeric(10, 2) not null default 50 check (min_prize_usd >= 0),
    max_effort_hours   numeric(6, 2) not null default 72 check (max_effort_hours > 0),
    -- Skills, languages, tools, cloud accounts, interests, owned datasets.
    profile            jsonb not null default '{}'::jsonb,
    updated_at         timestamptz not null default now(),
    check (soft_warn_usd < pause_usd and pause_usd < monthly_cap_usd)
);
insert into public.settings (id) values (1);

-- ---------------------------------------------------------------------------
-- Sources and events
-- ---------------------------------------------------------------------------

create table public.sources (
    id                   text primary key,
    name                 text not null,
    base_url             text not null,
    -- Disabled until the owner has reviewed the site's terms of use.
    enabled              boolean not null default false,
    terms_reviewed_at    timestamptz,
    terms_notes          text,
    last_run_at          timestamptz,
    last_status          text check (last_status in ('ok', 'error')),
    last_error           text,
    consecutive_failures integer not null default 0,
    constraint enabled_requires_terms check (not enabled or terms_reviewed_at is not null)
);
insert into public.sources (id, name, base_url) values
    ('devpost', 'Devpost', 'https://devpost.com'),
    ('mlh', 'Major League Hacking', 'https://mlh.io'),
    ('devfolio', 'Devfolio', 'https://devfolio.co');

create type public.event_status as enum (
    'discovered',          -- stored by Discovery
    'analyzed',            -- rules parsed
    'filtered_out',        -- failed a hard filter
    'below_threshold',     -- scored under the surface threshold
    'awaiting_approval',   -- GATE 1
    'approved',
    'rejected',
    'deferred',
    'planning',
    'plan_ready',          -- GATE 2
    'plan_approved',
    'building',
    'awaiting_input',      -- GATE 3
    'paused_budget',       -- token budget exceeded, waiting on owner
    'in_review',
    'submission_ready',    -- GATE 4
    'submitted',
    'results_in',
    'closed',
    'duplicate'
);

create table public.events (
    id                    uuid primary key default gen_random_uuid(),
    source_id             text not null references public.sources (id),
    external_id           text not null,
    dedupe_key            text not null,
    duplicate_of          uuid references public.events (id),
    title                 text not null check (char_length(title) <= 300),
    url                   text not null check (url ~ '^https://'),
    organizer             text,
    starts_at             timestamptz,
    submission_deadline   timestamptz,
    registration_deadline timestamptz,
    prize_text            text,
    cash_value_usd        numeric(12, 2),
    prize_value_known     boolean not null default false,
    is_online             boolean,
    themes                text[] not null default '{}',
    registrants           integer,
    status                public.event_status not null default 'discovered',
    -- Status to return to when a budget pause is lifted.
    paused_from           public.event_status,
    raw                   jsonb not null default '{}'::jsonb,
    first_seen_at         timestamptz not null default now(),
    last_seen_at          timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    unique (source_id, external_id)
);
create index events_status_idx on public.events (status);
create index events_dedupe_idx on public.events (dedupe_key);
create index events_deadline_idx on public.events (submission_deadline);

create table public.event_rules (
    id                  uuid primary key default gen_random_uuid(),
    event_id            uuid not null references public.events (id) on delete cascade,
    content_hash        text not null,
    source_url          text not null,
    snapshot            text not null,
    fetched_at          timestamptz not null default now(),
    summary             text,
    requirements        jsonb not null default '[]'::jsonb,
    eligibility         jsonb not null default '{}'::jsonb,
    ai_policy           text not null default 'unclear'
        check (ai_policy in ('allowed', 'allowed_with_disclosure', 'restricted', 'prohibited', 'unclear')),
    ai_policy_notes     text,
    disclosure_format   text,
    solo_allowed        boolean,
    online_only         boolean,
    max_team_size       integer,
    prizes              jsonb not null default '{}'::jsonb,
    submission_format   jsonb not null default '{}'::jsonb,
    judging_criteria    jsonb not null default '[]'::jsonb,
    deadlines           jsonb not null default '{}'::jsonb,
    required_resources  jsonb not null default '[]'::jsonb,
    risks               jsonb not null default '[]'::jsonb,
    ambiguities         jsonb not null default '[]'::jsonb,
    model               text,
    created_at          timestamptz not null default now(),
    unique (event_id, content_hash)
);
create index event_rules_event_idx on public.event_rules (event_id, created_at desc);

create table public.scores (
    id                   uuid primary key default gen_random_uuid(),
    event_id             uuid not null references public.events (id) on delete cascade,
    total                numeric(5, 2) not null check (total between 0 and 100),
    factors              jsonb not null,
    hard_filters         jsonb not null,
    passed_hard_filters  boolean not null,
    est_hours            numeric(6, 2),
    model_version        text not null,
    reason               text,
    created_at           timestamptz not null default now()
);
create index scores_event_idx on public.scores (event_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Plans, milestones, inputs
-- ---------------------------------------------------------------------------

create table public.plans (
    id               uuid primary key default gen_random_uuid(),
    event_id         uuid not null references public.events (id) on delete cascade,
    version          integer not null default 1,
    status           text not null default 'draft'
        check (status in ('draft', 'ready', 'approved', 'revision_requested', 'superseded')),
    problem          text,
    angle            text,
    summary          text,
    local_context    text,
    total_hours      numeric(6, 2),
    skills           text[] not null default '{}',
    inputs_needed    jsonb not null default '[]'::jsonb,
    disclosure_draft text,
    risks            jsonb not null default '[]'::jsonb,
    warnings         jsonb not null default '[]'::jsonb,
    revision_notes   text,
    model            text,
    created_at       timestamptz not null default now(),
    approved_at      timestamptz,
    unique (event_id, version)
);

create table public.milestones (
    id             uuid primary key default gen_random_uuid(),
    plan_id        uuid not null references public.plans (id) on delete cascade,
    event_id       uuid not null references public.events (id) on delete cascade,
    seq            integer not null,
    title          text not null,
    description    text,
    est_hours      numeric(6, 2) not null default 0 check (est_hours >= 0),
    actual_hours   numeric(6, 2) check (actual_hours >= 0),
    skills         text[] not null default '{}',
    input_keys     text[] not null default '{}',
    needs_top_tier boolean not null default false,
    model_tier     text,
    test_report    jsonb,
    status         text not null default 'pending'
        check (status in ('pending', 'blocked', 'in_progress', 'drafted', 'done', 'skipped', 'failed')),
    notes          text,
    updated_at     timestamptz not null default now(),
    unique (plan_id, seq)
);

create table public.input_requests (
    id            uuid primary key default gen_random_uuid(),
    event_id      uuid not null references public.events (id) on delete cascade,
    plan_id       uuid references public.plans (id) on delete cascade,
    key           text not null,
    kind          text not null check (kind in (
        'credential_setup', 'dataset', 'decision', 'anecdote', 'account_access',
        'budget_extension', 'top_tier_approval', 'other')),
    description   text not null,
    status        text not null default 'pending' check (status in ('pending', 'answered', 'declined')),
    response      text check (char_length(response) <= 10000),
    responded_at  timestamptz,
    created_at    timestamptz not null default now(),
    unique (event_id, key)
);

-- ---------------------------------------------------------------------------
-- Skills, datasets, artifacts
-- ---------------------------------------------------------------------------

create table public.skills (
    id             text primary key,
    name           text not null,
    purpose        text not null,
    inputs         jsonb not null default '[]'::jsonb,
    outputs        jsonb not null default '[]'::jsonb,
    cost_notes     text,
    enabled        boolean not null default true,
    usage_count    integer not null default 0,
    success_count  integer not null default 0
);

create table public.datasets (
    id          uuid primary key default gen_random_uuid(),
    event_id    uuid not null references public.events (id) on delete cascade,
    plan_id     uuid references public.plans (id) on delete cascade,
    name        text not null,
    source      text not null,
    url         text,
    license     text,
    license_ok  boolean,
    owner_data  boolean not null default false,
    approved    boolean not null default false,
    notes       text,
    created_at  timestamptz not null default now()
);

create table public.artifacts (
    id            uuid primary key default gen_random_uuid(),
    event_id      uuid not null references public.events (id) on delete cascade,
    milestone_id  uuid references public.milestones (id) on delete set null,
    path          text not null,
    storage_path  text not null,
    skill_id      text references public.skills (id),
    content_type  text not null,
    size_bytes    integer not null,
    sha256        text not null,
    -- First few thousand characters of text artifacts, for the Reviewer.
    excerpt       text,
    created_at    timestamptz not null default now(),
    unique (event_id, path)
);
create index artifacts_event_idx on public.artifacts (event_id);

-- ---------------------------------------------------------------------------
-- Decisions (gates), submissions, results, learning
-- ---------------------------------------------------------------------------

create table public.decisions (
    id          uuid primary key default gen_random_uuid(),
    event_id    uuid not null references public.events (id) on delete cascade,
    gate        text not null check (gate in ('event', 'plan', 'submission')),
    decision    text not null check (decision in ('approve', 'reject', 'defer', 'revise')),
    plan_id     uuid references public.plans (id),
    reason      text check (char_length(reason) <= 4000),
    created_by  uuid default auth.uid(),
    created_at  timestamptz not null default now()
);
create index decisions_event_idx on public.decisions (event_id, created_at desc);

create table public.submissions (
    id            uuid primary key default gen_random_uuid(),
    event_id      uuid not null references public.events (id) on delete cascade,
    plan_id       uuid references public.plans (id),
    version       integer not null default 1,
    package       jsonb not null default '{}'::jsonb,
    disclosure    text not null check (char_length(disclosure) > 0),
    checklist     jsonb not null default '[]'::jsonb,
    review_notes  jsonb not null default '[]'::jsonb,
    blocking_issues jsonb not null default '[]'::jsonb,
    status        text not null default 'draft' check (status in ('draft', 'ready', 'submitted', 'withdrawn')),
    submitted_at  timestamptz,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    unique (event_id, version)
);

create table public.results (
    id              uuid primary key default gen_random_uuid(),
    event_id        uuid not null unique references public.events (id) on delete cascade,
    placement       integer check (placement > 0),
    placement_text  text,
    prize_won_usd   numeric(12, 2) not null default 0 check (prize_won_usd >= 0),
    judge_feedback  text,
    platform_notes  text,
    entered_at      timestamptz not null default now()
);

create table public.learnings (
    id              uuid primary key default gen_random_uuid(),
    event_id        uuid not null unique references public.events (id) on delete cascade,
    went_well       text not null default '',
    would_change    text not null default '',
    carry_forward   text not null default '',
    status          text not null default 'draft' check (status in ('draft', 'approved')),
    drafted_by      text,
    approved_at     timestamptz,
    updated_at      timestamptz not null default now()
);

create table public.playbook (
    id               uuid primary key default gen_random_uuid(),
    lesson           text not null check (char_length(lesson) <= 500),
    source_event_ids uuid[] not null default '{}',
    status           text not null default 'proposed' check (status in ('proposed', 'active', 'retired')),
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Alerts, spend, runs
-- ---------------------------------------------------------------------------

create table public.alerts (
    id             uuid primary key default gen_random_uuid(),
    kind           text not null check (kind in (
        'event_awaiting_approval', 'plan_ready', 'input_needed', 'submission_ready',
        'deadline_48h', 'weekly_summary', 'monthly_summary', 'budget', 'source_failure', 'info')),
    title          text not null,
    body           text,
    event_id       uuid references public.events (id) on delete cascade,
    dedupe_key     text not null unique,
    read_at        timestamptz,
    snoozed_until  timestamptz,
    created_at     timestamptz not null default now()
);
create index alerts_unread_idx on public.alerts (created_at desc) where read_at is null;

create table public.spend_log (
    id                     bigint generated always as identity primary key,
    run_id                 uuid,
    agent                  text not null,
    event_id               uuid references public.events (id) on delete set null,
    model                  text not null,
    input_tokens           integer not null default 0,
    output_tokens          integer not null default 0,
    cache_creation_tokens  integer not null default 0,
    cache_read_tokens      integer not null default 0,
    cost_usd               numeric(10, 6) not null check (cost_usd >= 0),
    batch                  boolean not null default false,
    purpose                text,
    request_id             text,
    created_at             timestamptz not null default now()
);
create index spend_log_created_idx on public.spend_log (created_at);
create index spend_log_event_idx on public.spend_log (event_id);

create table public.agent_runs (
    id           uuid primary key default gen_random_uuid(),
    agent        text not null,
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    status       text not null default 'running' check (status in ('running', 'ok', 'error', 'skipped')),
    stats        jsonb not null default '{}'::jsonb,
    error        text
);

-- ---------------------------------------------------------------------------
-- Views (security_invoker so RLS of the caller applies)
-- ---------------------------------------------------------------------------

create view public.month_spend with (security_invoker = true) as
select
    coalesce(sum(cost_usd), 0)::numeric(10, 6) as month_to_date_usd,
    -- Linear projection to month end.
    (coalesce(sum(cost_usd), 0)
        / greatest(extract(epoch from now() - date_trunc('month', now())), 3600)
        * extract(epoch from (date_trunc('month', now()) + interval '1 month') - date_trunc('month', now()))
    )::numeric(10, 6) as projected_usd
from public.spend_log
where created_at >= date_trunc('month', now());

create view public.event_spend with (security_invoker = true) as
select event_id, sum(cost_usd)::numeric(10, 6) as spent_usd
from public.spend_log
where event_id is not null
group by event_id;

-- ---------------------------------------------------------------------------
-- Gate enforcement
-- ---------------------------------------------------------------------------

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger events_touch before update on public.events
    for each row execute function public.touch_updated_at();
create trigger milestones_touch before update on public.milestones
    for each row execute function public.touch_updated_at();
create trigger submissions_touch before update on public.submissions
    for each row execute function public.touch_updated_at();
create trigger learnings_touch before update on public.learnings
    for each row execute function public.touch_updated_at();
create trigger settings_touch before update on public.settings
    for each row execute function public.touch_updated_at();

create or replace function public.gate_open()
returns boolean language sql stable as $$
    select coalesce(current_setting('hackagent.gate', true), '') = 'on';
$$;

-- Event statuses that only a gate decision may set.
create or replace function public.guard_event_status()
returns trigger language plpgsql as $$
begin
    if new.status is distinct from old.status
       and new.status in ('approved', 'rejected', 'deferred', 'plan_approved', 'submitted')
       and not public.gate_open() then
        raise exception 'Event status % can only be set by an owner decision', new.status
            using errcode = '42501';
    end if;
    return new;
end;
$$;
create trigger events_guard_status before update on public.events
    for each row execute function public.guard_event_status();

create or replace function public.guard_plan_status()
returns trigger language plpgsql as $$
begin
    if new.status is distinct from old.status
       and new.status in ('approved', 'revision_requested')
       and not public.gate_open() then
        raise exception 'Plan status % can only be set by an owner decision', new.status
            using errcode = '42501';
    end if;
    return new;
end;
$$;
create trigger plans_guard_status before update on public.plans
    for each row execute function public.guard_plan_status();

create or replace function public.guard_submission_status()
returns trigger language plpgsql as $$
begin
    if (new.status is distinct from old.status and new.status = 'submitted'
        or new.submitted_at is distinct from old.submitted_at)
       and not public.gate_open() then
        raise exception 'Only the owner can confirm a submission' using errcode = '42501';
    end if;
    return new;
end;
$$;
create trigger submissions_guard_status before update on public.submissions
    for each row execute function public.guard_submission_status();

create or replace function public.guard_input_response()
returns trigger language plpgsql as $$
begin
    if new.status is distinct from old.status and new.status in ('answered', 'declined')
       or new.response is distinct from old.response then
        perform public.require_owner('answer an input request');
        new.responded_at := now();
    end if;
    return new;
end;
$$;
create trigger input_requests_guard before update on public.input_requests
    for each row execute function public.guard_input_response();

create or replace function public.guard_learning_approval()
returns trigger language plpgsql as $$
begin
    if new.status = 'approved' and (tg_op = 'INSERT' or old.status is distinct from 'approved') then
        perform public.require_owner('approve a learning record');
        new.approved_at := now();
    end if;
    return new;
end;
$$;
create trigger learnings_guard before insert or update on public.learnings
    for each row execute function public.guard_learning_approval();

create or replace function public.guard_playbook_activation()
returns trigger language plpgsql as $$
begin
    if new.status = 'active' and (tg_op = 'INSERT' or old.status is distinct from 'active') then
        perform public.require_owner('activate a playbook lesson');
    end if;
    return new;
end;
$$;
create trigger playbook_guard before insert or update on public.playbook
    for each row execute function public.guard_playbook_activation();

create or replace function public.guard_results()
returns trigger language plpgsql as $$
begin
    perform public.require_owner('record results');
    return new;
end;
$$;
create trigger results_guard before insert or update on public.results
    for each row execute function public.guard_results();

-- Decisions: owner-only, validated against the current state, and applied
-- atomically so the gate cannot be half-open.
create or replace function public.apply_decision()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    ev public.events%rowtype;
    pl public.plans%rowtype;
    sub_id uuid;
begin
    perform public.require_owner('make a decision');
    new.created_by := auth.uid();

    select * into ev from public.events where id = new.event_id for update;
    if not found then
        raise exception 'Unknown event %', new.event_id;
    end if;

    perform set_config('hackagent.gate', 'on', true);

    if new.gate = 'event' then
        if ev.status not in ('awaiting_approval', 'deferred', 'below_threshold') then
            raise exception 'Event is not awaiting a decision (status %)', ev.status;
        end if;
        if new.decision = 'approve' then
            update public.events set status = 'approved' where id = ev.id;
        elsif new.decision = 'reject' then
            if coalesce(trim(new.reason), '') = '' then
                raise exception 'A rejection needs a reason (it feeds back into scoring)';
            end if;
            update public.events set status = 'rejected' where id = ev.id;
        elsif new.decision = 'defer' then
            update public.events set status = 'deferred' where id = ev.id;
        else
            raise exception 'Decision % is not valid for the event gate', new.decision;
        end if;

    elsif new.gate = 'plan' then
        select * into pl from public.plans where id = new.plan_id and event_id = ev.id for update;
        if not found or pl.status <> 'ready' or ev.status <> 'plan_ready' then
            raise exception 'No plan is ready for review on this event';
        end if;
        if new.decision = 'approve' then
            update public.plans set status = 'approved', approved_at = now() where id = pl.id;
            update public.events set status = 'plan_approved' where id = ev.id;
        elsif new.decision = 'revise' then
            update public.plans set status = 'revision_requested', revision_notes = new.reason
                where id = pl.id;
            update public.events set status = 'planning' where id = ev.id;
        elsif new.decision = 'reject' then
            update public.plans set status = 'superseded' where id = pl.id;
            update public.events set status = 'rejected' where id = ev.id;
        else
            raise exception 'Decision % is not valid for the plan gate', new.decision;
        end if;

    elsif new.gate = 'submission' then
        select id into sub_id from public.submissions
            where event_id = ev.id and status = 'ready'
            order by version desc limit 1 for update;
        if sub_id is null or ev.status <> 'submission_ready' then
            raise exception 'No submission package is ready on this event';
        end if;
        if new.decision = 'approve' then
            -- The owner confirms they submitted manually on the platform.
            update public.submissions set status = 'submitted', submitted_at = now() where id = sub_id;
            update public.events set status = 'submitted' where id = ev.id;
        elsif new.decision = 'revise' then
            update public.submissions set status = 'draft',
                review_notes = review_notes || jsonb_build_array(jsonb_build_object(
                    'from', 'owner', 'note', coalesce(new.reason, ''), 'at', now()))
                where id = sub_id;
            update public.events set status = 'in_review' where id = ev.id;
        elsif new.decision = 'reject' then
            update public.submissions set status = 'withdrawn' where id = sub_id;
            update public.events set status = 'closed' where id = ev.id;
        else
            raise exception 'Decision % is not valid for the submission gate', new.decision;
        end if;
    end if;

    perform set_config('hackagent.gate', 'off', true);
    return new;
end;
$$;
create trigger decisions_apply before insert on public.decisions
    for each row execute function public.apply_decision();

-- Decisions are an audit log: never edited or removed.
create or replace function public.forbid_change()
returns trigger language plpgsql as $$
begin
    raise exception '% rows are append-only', tg_table_name using errcode = '42501';
end;
$$;
create trigger decisions_append_only before update or delete on public.decisions
    for each row execute function public.forbid_change();

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

do $$
declare
    t text;
begin
    foreach t in array array[
        'app_owner', 'settings', 'sources', 'events', 'event_rules', 'scores', 'plans',
        'milestones', 'input_requests', 'skills', 'datasets', 'artifacts', 'decisions',
        'submissions', 'results', 'learnings', 'playbook', 'alerts', 'spend_log', 'agent_runs'
    ] loop
        execute format('alter table public.%I enable row level security', t);
        execute format('alter table public.%I force row level security', t);
        execute format('revoke all on public.%I from anon', t);
        execute format(
            'create policy owner_select on public.%I for select to authenticated using (public.is_owner())', t);
    end loop;

    -- Tables the owner edits from the dashboard.
    foreach t in array array[
        'settings', 'sources', 'events', 'plans', 'milestones', 'input_requests', 'skills',
        'datasets', 'submissions', 'results', 'learnings', 'playbook', 'alerts'
    ] loop
        execute format(
            'create policy owner_update on public.%I for update to authenticated '
            'using (public.is_owner()) with check (public.is_owner())', t);
    end loop;

    -- Tables the owner inserts into from the dashboard.
    foreach t in array array['decisions', 'results', 'learnings', 'playbook'] loop
        execute format(
            'create policy owner_insert on public.%I for insert to authenticated '
            'with check (public.is_owner())', t);
    end loop;
end;
$$;

revoke all on function public.is_owner() from anon;
revoke all on function public.require_owner(text) from anon, authenticated;
revoke all on function public.apply_decision() from anon, authenticated;
revoke select on public.month_spend, public.event_spend from anon;

-- ---------------------------------------------------------------------------
-- Storage: private bucket for artifacts and submission packages
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public, file_size_limit)
values ('artifacts', 'artifacts', false, 10485760)
on conflict (id) do nothing;

create policy artifacts_owner_read on storage.objects
    for select to authenticated
    using (bucket_id = 'artifacts' and public.is_owner());

-- ---------------------------------------------------------------------------
-- Results and performance analytics (section 9)
-- ---------------------------------------------------------------------------

create or replace function public.results_mark_event()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    update public.events set status = 'results_in'
    where id = new.event_id and status in ('submitted', 'closed');
    return new;
end;
$$;
create trigger results_mark_event after insert on public.results
    for each row execute function public.results_mark_event();
revoke all on function public.results_mark_event() from anon, authenticated;

-- One row per event that reached planning, for the performance dashboard.
create view public.event_performance with (security_invoker = true) as
select
    e.id as event_id,
    e.title,
    e.source_id,
    e.themes,
    e.status,
    e.submission_deadline,
    s.submitted_at,
    coalesce(m.planned_hours, 0) as planned_hours,
    coalesce(m.actual_hours, 0) as actual_hours,
    m.milestones_with_actuals,
    coalesce(sp.spent_usd, 0) as spent_usd,
    r.placement,
    coalesce(r.prize_won_usd, 0) as prize_won_usd,
    (r.placement is not null and r.placement <= 3) or coalesce(r.prize_won_usd, 0) > 0 as placed
from public.events e
left join lateral (
    select sum(est_hours) as planned_hours,
           sum(actual_hours) as actual_hours,
           count(actual_hours) as milestones_with_actuals
    from public.milestones mm
    join public.plans p on p.id = mm.plan_id and p.status = 'approved'
    where mm.event_id = e.id
) m on true
left join lateral (
    select max(submitted_at) as submitted_at from public.submissions
    where event_id = e.id and status = 'submitted'
) s on true
left join public.event_spend sp on sp.event_id = e.id
left join public.results r on r.event_id = e.id
where exists (select 1 from public.plans p2 where p2.event_id = e.id);

revoke select on public.event_performance from anon;
