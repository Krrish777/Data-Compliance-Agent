import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";

// Serves compliance report artifacts from ../data/ (PDF / HTML) to the dashboard.
// The [...path] catch-all segment contains the relative path returned by the
// backend graph in state.report_paths, which is typically an absolute path
// on the developer's machine. We only allow paths that resolve under the
// repo's data/ directory for safety.

const PROJECT_ROOT = path.resolve(process.cwd(), "..");
const DATA_DIR = path.join(PROJECT_ROOT, "data");

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: rawSegments } = await params;
  const raw = decodeURIComponent((rawSegments || []).join("/"));

  // Normalize: if the path is absolute, trust it only when it lands inside data/.
  const candidate = path.isAbsolute(raw) ? raw : path.join(DATA_DIR, raw);
  const resolved = path.resolve(candidate);

  if (!resolved.startsWith(DATA_DIR + path.sep) && resolved !== DATA_DIR) {
    return NextResponse.json({ error: "Path outside data/ is forbidden" }, { status: 403 });
  }

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
  } catch (e) {
    return NextResponse.json(
      { error: `Report not found: ${e instanceof Error ? e.message : String(e)}` },
      { status: 404 },
    );
  }
}
