import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";

// Serves compliance report artifacts from ../data/ (PDF / HTML) to the dashboard.
// The [...path] catch-all segment contains whatever the backend graph put in
// state.report_paths.pdf / .html — on Windows that's typically a relative
// path with backslashes like "data\compliance_report_xxx.pdf", and on Unix
// it's a forward-slash relative path. We also accept absolute paths and bare
// basenames. Anything that resolves outside data/ is rejected.

const PROJECT_ROOT = path.resolve(process.cwd(), "..");
const DATA_DIR = path.resolve(path.join(PROJECT_ROOT, "data"));

function normalize(raw: string): string {
  // Collapse Windows backslashes to forward slashes for portable path.* calls.
  return raw.replace(/\\/g, "/");
}

function resolveUnderDataDir(raw: string): string | null {
  const candidate = path.isAbsolute(raw) ? raw : path.join(DATA_DIR, raw);
  const resolved = path.resolve(candidate);
  if (resolved === DATA_DIR || resolved.startsWith(DATA_DIR + path.sep)) {
    return resolved;
  }
  return null;
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: rawSegments } = await params;
  const joined = (rawSegments || []).map(decodeURIComponent).join("/");
  const raw = normalize(joined);

  // Try candidates in order:
  //   1. the exact path as given (relative or absolute)
  //   2. the basename resolved inside DATA_DIR
  //      — covers backends that prefix "data/" when DATA_DIR is already "data"
  const candidates: (string | null)[] = [
    resolveUnderDataDir(raw),
    resolveUnderDataDir(path.basename(raw)),
  ];

  for (const resolved of candidates) {
    if (!resolved) continue;
    try {
      const file = await fs.readFile(resolved);
      const ext = path.extname(resolved).toLowerCase();
      const contentType =
        ext === ".pdf"  ? "application/pdf" :
        ext === ".html" ? "text/html; charset=utf-8" :
                          "application/octet-stream";
      const basename = path.basename(resolved);
      return new NextResponse(new Uint8Array(file), {
        status: 200,
        headers: {
          "Content-Type": contentType,
          "Content-Disposition": `inline; filename="${basename}"`,
          "Cache-Control": "no-store",
        },
      });
    } catch {
      // fall through to next candidate
    }
  }

  // Last-ditch: if caller passed a scan_id or base filename that matches something
  // already on disk, offer a helpful 404 listing what we did look at.
  return NextResponse.json(
    {
      error: "Report not found",
      tried: candidates.filter(Boolean),
      requested: raw,
      dataDir: DATA_DIR,
    },
    { status: 404 },
  );
}
