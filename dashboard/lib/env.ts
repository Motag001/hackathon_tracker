// Read once and validated so a misconfigured deployment fails loudly.
function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing environment variable ${name}`);
  return value;
}

export const SUPABASE_URL = required(
  "NEXT_PUBLIC_SUPABASE_URL",
  process.env.NEXT_PUBLIC_SUPABASE_URL,
);
export const SUPABASE_ANON_KEY = required(
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
);

if (!SUPABASE_URL.startsWith("https://") && !/^http:\/\/(127\.0\.0\.1|localhost)/.test(SUPABASE_URL)) {
  throw new Error("NEXT_PUBLIC_SUPABASE_URL must use https://");
}
