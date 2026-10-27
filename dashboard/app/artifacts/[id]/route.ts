import { NextResponse } from "next/server";

import { requireOwner } from "@/lib/auth";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Download an artifact through a short-lived signed URL. Files are always
 * served as downloads, never rendered in the dashboard's origin.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) return new NextResponse("Not found", { status: 404 });
  const { supabase } = await requireOwner();
  const { data: art } = await supabase
    .from("artifacts")
    .select("storage_path,path")
    .eq("id", id)
    .maybeSingle();
  if (!art) return new NextResponse("Not found", { status: 404 });

  const [bucket, ...rest] = String(art.storage_path).split("/");
  if (bucket !== "artifacts" || !rest.length) return new NextResponse("Not found", { status: 404 });
  const filename = String(art.path).split("/").pop() ?? "artifact";
  const { data, error } = await supabase.storage
    .from(bucket)
    .createSignedUrl(rest.join("/"), 60, { download: filename });
  if (error || !data) return new NextResponse("Unavailable", { status: 502 });
  return NextResponse.redirect(data.signedUrl, { status: 303 });
}
