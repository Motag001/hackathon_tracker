// Row shapes used by the dashboard (subset of the database columns).

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

export interface EventRow {
  id: string;
  source_id: string;
  title: string;
  url: string;
  organizer: string | null;
  status: string;
  submission_deadline: string | null;
  registration_deadline: string | null;
  prize_text: string | null;
  cash_value_usd: string | null;
  themes: string[];
  registrants: number | null;
  raw: { filter_reason?: string } & Record<string, Json>;
  first_seen_at: string;
}

export interface Factor {
  value: number;
  weight: number;
  points: number;
  reason: string;
}

export interface ScoreRow {
  total: number;
  factors: Record<string, Factor | Record<string, Json>>;
  hard_filters: { name: string; passed: boolean; detail: string }[];
  passed_hard_filters: boolean;
  est_hours: number | null;
  reason: string | null;
  model_version: string;
  created_at: string;
}

export interface AlertRow {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  event_id: string | null;
  read_at: string | null;
  snoozed_until: string | null;
  created_at: string;
}
