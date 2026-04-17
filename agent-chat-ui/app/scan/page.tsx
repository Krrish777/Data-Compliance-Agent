"use client";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { Upload, FileText, Play } from "lucide-react";

import { getClient, ASSISTANT_ID, PIPELINE_STAGES, type StageId } from "@/lib/langgraph";
import { Timeline, type StageStatus } from "@/components/Timeline";
import { HitlModal, type LowConfidenceRule } from "@/components/HitlModal";

const DEFAULT_DB = "data/HI-Small_Trans.db";
const DEFAULT_PDF = "data/AML_Compliance_Policy.pdf";

type LogLine = { at: string; stage?: string; detail: string };

export default function ScanPage() {
  const router = useRouter();

  const [policyPath, setPolicyPath]   = useState<string>(DEFAULT_PDF);
  const [dbPath, setDbPath]           = useState<string>(DEFAULT_DB);
  const [uploadedName, setUploaded]   = useState<string | null>(null);

  const [running, setRunning]         = useState(false);
  const [threadId, setThreadId]       = useState<string | null>(null);

  const initialStatus = useMemo(
    () => Object.fromEntries(PIPELINE_STAGES.map((s) => [s.id, "pending" as StageStatus])) as Record<StageId, StageStatus>,
    [],
  );
  const [stageStatus, setStageStatus] = useState<Record<StageId, StageStatus>>(initialStatus);
  const [logs, setLogs]               = useState<LogLine[]>([]);

  const [hitlPayload, setHitlPayload] = useState<
    | { rules: LowConfidenceRule[]; message: string; interruptId?: string }
    | null
  >(null);

  const onDrop = useCallback((accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setUploaded(f.name);
    setPolicyPath(`uploaded:${f.name}`);
    toast.info(
      "Upload recorded. For the demo we'll still use the canonical AML PDF at " +
        DEFAULT_PDF +
        " — backend reads from a file path.",
    );
    setPolicyPath(DEFAULT_PDF);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  const setStage = useCallback((id: string, status: StageStatus) => {
    setStageStatus((prev) => ({ ...prev, [id as StageId]: status }));
  }, []);

  const pushLog = useCallback((line: LogLine) => {
    setLogs((prev) => [...prev.slice(-200), line]);
  }, []);

  const runScan = async () => {
    const client = getClient();
    setRunning(true);
    setStageStatus(initialStatus);
    setLogs([]);
    setHitlPayload(null);

    try {
      const thread = await client.threads.create();
      setThreadId(thread.thread_id);
      pushLog({ at: "start", detail: `Thread ${thread.thread_id} opened` });

      const input = {
        document_path: policyPath,
        db_type: "sqlite",
        db_config: { db_path: dbPath },
        violations_db_path: "data/hi_small_violations.db",
        batch_size: 500,
        errors: [],
        raw_rules: [],
      };

      await streamRun(client, thread.thread_id, input);
    } catch (e) {
      toast.error(`Run failed: ${e instanceof Error ? e.message : String(e)}`);
      setRunning(false);
    }
  };

  const streamRun = async (
    client: ReturnType<typeof getClient>,
    tid: string,
    input: unknown,
  ) => {
    const stream = client.runs.stream(tid, ASSISTANT_ID, {
      input: input as Record<string, unknown>,
      streamMode: ["updates", "messages", "custom"],
      streamSubgraphs: true,
    });

    for await (const evt of stream) {
      handleEvent(evt);
    }

    const state = await client.threads.getState(tid);
    const reportPaths = (state.values as { report_paths?: { pdf?: string; html?: string } })
      ?.report_paths;
    if (reportPaths?.pdf || reportPaths?.html) {
      toast.success("Scan complete — redirecting to dashboard…");
      router.push(`/dashboard/${tid}`);
    } else {
      toast.warning("Scan finished without a report. Check the log panel.");
      setRunning(false);
    }
  };

  const handleEvent = (evt: { event: string; data: unknown }) => {
    const { event, data } = evt;
    if (event === "updates" && data && typeof data === "object") {
      for (const key of Object.keys(data as Record<string, unknown>)) {
        if (key === "__interrupt__") {
          const payload = (data as Record<string, unknown>)[key] as unknown;
          const first = Array.isArray(payload) ? (payload[0] as Record<string, unknown>) : (payload as Record<string, unknown>);
          const value = (first?.value as Record<string, unknown>) || first;
          setStage("human_review", "waiting");
          setHitlPayload({
            rules: (value?.rules as LowConfidenceRule[]) || [],
            message:
              (value?.message as string) ||
              "Low-confidence rules need your review.",
            interruptId: (first?.interrupt_id as string) || undefined,
          });
          pushLog({ at: "interrupt", stage: "human_review", detail: "waiting for human decision" });
        } else {
          setStage(key, "done");
          pushLog({ at: "node", stage: key, detail: `${key} completed` });
          bumpNextRunning(key);
        }
      }
    } else if (event === "error") {
      const msg = (data as { message?: string })?.message || "stream error";
      toast.error(msg);
      pushLog({ at: "error", detail: msg });
    }
  };

  const bumpNextRunning = (completedNodeId: string) => {
    const idx = PIPELINE_STAGES.findIndex((s) => s.id === completedNodeId);
    if (idx === -1 || idx === PIPELINE_STAGES.length - 1) return;
    const next = PIPELINE_STAGES[idx + 1].id;
    setStageStatus((prev) =>
      prev[next] === "pending" ? { ...prev, [next]: "running" } : prev,
    );
  };

  const resumeHitl = async (decision: unknown) => {
    if (!threadId) return;
    const client = getClient();
    setHitlPayload(null);
    setStage("human_review", "done");
    pushLog({ at: "resume", stage: "human_review", detail: "decision submitted, resuming graph" });

    const stream = client.runs.stream(threadId, ASSISTANT_ID, {
      command: { resume: decision },
      streamMode: ["updates", "messages", "custom"],
      streamSubgraphs: true,
    });

    for await (const evt of stream) handleEvent(evt);

    const state = await client.threads.getState(threadId);
    const reportPaths = (state.values as { report_paths?: { pdf?: string; html?: string } })
      ?.report_paths;
    if (reportPaths?.pdf || reportPaths?.html) {
      router.push(`/dashboard/${threadId}`);
    } else {
      setRunning(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-10">
      {/* LEFT: Controls */}
      <aside>
        <div className="caps-label mb-2">Audit Session</div>
        <h1 className="display-lg text-3xl mb-6">Configure the scan.</h1>

        <div className="bg-card border border-border p-5 rounded-sm mb-4">
          <div className="caps-label mb-2">Policy PDF</div>
          <div
            {...getRootProps()}
            className={`border border-dashed ${isDragActive ? "border-teal-deep bg-teal-wash" : "border-border-dark"} rounded-sm p-6 text-center cursor-pointer transition-colors`}
          >
            <input {...getInputProps()} />
            <Upload className="w-6 h-6 mx-auto mb-2 text-ink-muted" />
            <div className="text-sm">
              {uploadedName
                ? <span className="font-mono text-xs text-teal-deep">{uploadedName}</span>
                : isDragActive
                  ? "Drop the PDF here"
                  : "Drag a policy PDF, or click to select"}
            </div>
            <div className="caps-label mt-2">Default: {DEFAULT_PDF}</div>
          </div>
        </div>

        <div className="bg-card border border-border p-5 rounded-sm mb-4">
          <div className="caps-label mb-2">Target Database</div>
          <select
            value={dbPath}
            onChange={(e) => setDbPath(e.target.value)}
            className="w-full border border-border-dark px-3 py-2.5 rounded-sm bg-cream font-mono text-sm focus:outline-none focus:border-teal-deep"
            disabled={running}
          >
            <option value="data/HI-Small_Trans.db">data/HI-Small_Trans.db (AML demo)</option>
          </select>
          <div className="flex items-center gap-2 mt-3 text-xs text-ink-muted">
            <FileText className="w-3.5 h-3.5" />
            Keyset pagination · ~10k rows · Groq Llama3 live
          </div>
        </div>

        <button
          disabled={running}
          onClick={runScan}
          className="w-full bg-teal-deep text-cream px-6 py-4 rounded-sm text-sm tracking-wider uppercase hover:bg-teal-mid disabled:bg-ink-faint disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          <Play className="w-4 h-4" />
          {running ? "Scanning…" : "Run Compliance Scan"}
        </button>

        {logs.length > 0 && (
          <div className="mt-6 bg-card border border-border rounded-sm">
            <div className="caps-label p-3 border-b border-border">Live Log</div>
            <div className="p-3 max-h-72 overflow-y-auto font-mono text-[11px] text-ink-secondary space-y-1">
              {logs.slice(-40).map((l, i) => (
                <div key={i}>
                  <span className="text-ink-faint">{l.at}</span>
                  {l.stage && <span className="text-teal-deep"> · {l.stage}</span>}
                  <span> · {l.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>

      {/* RIGHT: Timeline */}
      <section>
        <div className="caps-label mb-2">The Pipeline</div>
        <h2 className="display-lg text-3xl mb-8">Nine stages — witnessed in real time.</h2>
        <Timeline stageStatus={stageStatus} />
      </section>

      {hitlPayload && (
        <HitlModal
          rules={hitlPayload.rules}
          message={hitlPayload.message}
          onResume={resumeHitl}
        />
      )}
    </div>
  );
}
