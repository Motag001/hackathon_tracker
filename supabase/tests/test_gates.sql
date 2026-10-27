-- Gate enforcement tests. Run after supabase_stub.sql and the migrations.
-- Any failed expectation raises and aborts with a non-zero exit code.
\set ON_ERROR_STOP on

insert into auth.users values ('00000000-0000-0000-0000-000000000001'), ('00000000-0000-0000-0000-000000000002');
insert into public.app_owner values ('00000000-0000-0000-0000-000000000001');

create or replace function pg_temp.expect_error(sql text, label text) returns void language plpgsql as $$
begin
    begin
        execute sql;
    exception when others then
        raise notice 'ok (rejected): % -> %', label, sqlerrm;
        return;
    end;
    raise exception 'EXPECTED FAILURE DID NOT HAPPEN: %', label;
end $$;

-- A second owner is impossible.
select pg_temp.expect_error(
    $$insert into public.app_owner values ('00000000-0000-0000-0000-000000000002')$$, 'second owner');

-- Sources cannot be enabled without a terms review.
select pg_temp.expect_error($$update public.sources set enabled = true where id = 'devpost'$$, 'enable without terms');

insert into public.events (id, source_id, external_id, dedupe_key, title, url, status)
values ('10000000-0000-0000-0000-000000000001', 'devpost', 'x1', 'k1', 'Test Hack', 'https://x.devpost.com', 'awaiting_approval');

-- Agent context (no JWT subject): cannot self-approve, either directly or via decisions.
select pg_temp.expect_error(
    $$update public.events set status = 'approved' where id = '10000000-0000-0000-0000-000000000001'$$,
    'agent sets approved status');
select pg_temp.expect_error(
    $$insert into public.decisions (event_id, gate, decision) values ('10000000-0000-0000-0000-000000000001', 'event', 'approve')$$,
    'agent inserts decision');

-- A non-owner user cannot decide either.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select pg_temp.expect_error(
    $$insert into public.decisions (event_id, gate, decision) values ('10000000-0000-0000-0000-000000000001', 'event', 'approve')$$,
    'non-owner decision');

-- Owner: rejection without reason fails, approval works.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select pg_temp.expect_error(
    $$insert into public.decisions (event_id, gate, decision) values ('10000000-0000-0000-0000-000000000001', 'event', 'reject')$$,
    'reject without reason');
insert into public.decisions (event_id, gate, decision) values ('10000000-0000-0000-0000-000000000001', 'event', 'approve');
do $$ begin
    if (select status from public.events where id = '10000000-0000-0000-0000-000000000001') <> 'approved' then
        raise exception 'event not approved';
    end if;
    if current_setting('hackagent.gate', true) = 'on' then raise exception 'gate left open'; end if;
end $$;
select pg_temp.expect_error($$update public.decisions set reason = 'x'$$, 'decisions are append-only');

-- Plan gate.
select set_config('request.jwt.claim.sub', '', false);
update public.events set status = 'plan_ready' where id = '10000000-0000-0000-0000-000000000001';
insert into public.plans (id, event_id, status) values ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'ready');
select pg_temp.expect_error(
    $$update public.plans set status = 'approved' where id = '20000000-0000-0000-0000-000000000001'$$, 'agent approves plan');
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
insert into public.decisions (event_id, gate, decision, plan_id)
values ('10000000-0000-0000-0000-000000000001', 'plan', 'approve', '20000000-0000-0000-0000-000000000001');
do $$ begin
    if (select status from public.plans where id = '20000000-0000-0000-0000-000000000001') <> 'approved' then
        raise exception 'plan not approved';
    end if;
end $$;

-- Input requests: only the owner answers.
select set_config('request.jwt.claim.sub', '', false);
insert into public.input_requests (id, event_id, key, kind, description)
values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'anecdote', 'anecdote', 'A story');
select pg_temp.expect_error(
    $$update public.input_requests set status = 'answered', response = 'made up' where key = 'anecdote'$$, 'agent answers input');

-- Submission gate: agent cannot mark submitted; owner can confirm.
update public.events set status = 'submission_ready' where id = '10000000-0000-0000-0000-000000000001';
insert into public.submissions (event_id, disclosure, status) values ('10000000-0000-0000-0000-000000000001', 'AI used for drafts.', 'ready');
select pg_temp.expect_error($$update public.submissions set status = 'submitted'$$, 'agent marks submitted');
select pg_temp.expect_error($$update public.submissions set submitted_at = now()$$, 'agent sets submitted_at');
select pg_temp.expect_error(
    $$insert into public.submissions (event_id, version, disclosure) values ('10000000-0000-0000-0000-000000000001', 2, '')$$,
    'empty disclosure');
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
insert into public.decisions (event_id, gate, decision) values ('10000000-0000-0000-0000-000000000001', 'submission', 'approve');
do $$ begin
    if (select status from public.events where id = '10000000-0000-0000-0000-000000000001') <> 'submitted' then
        raise exception 'event not submitted';
    end if;
end $$;

-- Learnings and results are owner-approved.
select set_config('request.jwt.claim.sub', '', false);
insert into public.learnings (event_id, went_well) values ('10000000-0000-0000-0000-000000000001', 'draft');
select pg_temp.expect_error($$update public.learnings set status = 'approved'$$, 'agent approves learning');
select pg_temp.expect_error(
    $$insert into public.results (event_id, placement) values ('10000000-0000-0000-0000-000000000001', 1)$$, 'agent records results');
select pg_temp.expect_error(
    $$insert into public.playbook (lesson, status) values ('x', 'active')$$, 'agent activates playbook');

-- RLS: authenticated non-owner sees nothing; owner sees rows.
grant usage on schema public to authenticated;
grant select on all tables in schema public to authenticated;
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
do $$ begin
    if (select count(*) from public.events) <> 0 then raise exception 'RLS leak to non-owner'; end if;
end $$;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
do $$ begin
    if (select count(*) from public.events) <> 1 then raise exception 'owner cannot read events'; end if;
end $$;
reset role;

select 'ALL GATE TESTS PASSED' as result;
