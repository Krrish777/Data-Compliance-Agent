"use client";
import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";

import {
  getClient,
  ASSISTANT_ID,
  PIPELINE_STAGES,
  type StageId,
} from "@/lib/langgraph";
import {
  HitlStream,
  type LowConfidenceRule,
  type HitlDecision,
} from "@/components/HitlStream";

const DEFAULT_DB = "data/HI-Small_Trans.db";
const DEFAULT_PDF = "data/AML_Compliance_Policy.pdf";

const ROMAN: Record<number, string> = {
  0: "I", 1: "II", 2: "III", 3: "IV", 4: "V",
  5: "VI", 6: "VII", 7: "VIII", 8: "IX",
};

type StageStatus = "pending" | "running" | "done" | "waiting" | "error";

type StageDetail = {
  status: StageStatus;
  at?: string;           // HH:MM:SS stamp when state last changed
  summary?: string;      // short italic status line
  kv?: { key: string; val: string }[]; // key/value rows for expandable detail
};

type RunFinalState = {
  threadId: string;
  reportPdf?: string;
  reportHtml?: string;
  violations: number;
  tablesScanned: number;
  complianceScore?: number;
};

// ---------- Helpers ---------------------------------------------------------

const stamp = (): string => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

/**
 * Pull a human summary from a stage's state-patch payload.
 * LangGraph emits one key per completed node; the value is the partial state
 * patch that node returned. We read the fields we care about for each stage.
 */
function summarizeStage(
  stageId: string,
  payload: unknown,
): { summary: string; kv: { key: string; val: string }[] } | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const kv: { key: string; val: string }[] = [];

  const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
  const asRec = (v: unknown): Record<string, unknown> =>
    v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

  switch (stageId) {
    case "rule_extraction": {
      const raw = asList(p.raw_rules);
      const low = asList(p.low_confidence_rules);
      kv.push({ key: "rules extracted", val: String(raw.length) });
      if (low.length) kv.push({ key: "low confidence", val: String(low.length) });
      return {
        summary: `Read the policy and extracted ${raw.length} rules.`,
        kv,
      };
    }
    case "schema_discovery": {
      const meta = asRec(p.schema_metadata);
      const tables = asRec(meta.tables);
      const tableCount = Object.keys(tables).length;
      kv.push({ key: "tables", val: String(tableCount) });
      return {
        summary: `Surveyed the database — ${tableCount} table${tableCount === 1 ? "" : "s"}.`,
        kv,
      };
    }
    case "rule_structuring": {
      const sr = asList(p.structured_rules);
      kv.push({ key: "rules mapped", val: String(sr.length) });
      return {
        summary: `Mapped rules to columns and normalised operators.`,
        kv,
      };
    }
    case "human_review": {
      // The node echoes review_decision after HITL resume.
      const decision = asRec(p.review_decision);
      const approved = asList(decision.approved).length;
      const dropped = asList(decision.dropped).length;
      if (approved || dropped) {
        kv.push({ key: "approved", val: String(approved) });
        kv.push({ key: "dropped",  val: String(dropped) });
      }
      return {
        summary: approved || dropped
          ? `Your signatures recorded — ${approved} approved, ${dropped} dropped.`
          : `Reviewed; no low-confidence rules required a decision.`,
        kv,
      };
    }
    case "data_scanning": {
      const summary = asRec(p.scan_summary);
      const total = Number(summary.total_violations ?? 0);
      const tables = Number(summary.tables_scanned ?? 0);
      const rules = Number(summary.rules_processed ?? 0);
      kv.push({ key: "violations", val: total.toLocaleString() });
      kv.push({ key: "tables scanned", val: String(tables) });
      if (rules) kv.push({ key: "rules processed", val: String(rules) });
      return {
        summary: `Walked the ledger — ${total.toLocaleString()} violation${total === 1 ? "" : "s"} flagged.`,
        kv,
      };
    }
    case "violation_validator": {
      const v = asRec(p.validation_summary);
      const confirmed = Number(v.confirmed ?? 0);
      const rejected  = Number(v.rejected ?? 0);
      if (confirmed || rejected) {
        kv.push({ key: "confirmed", val: String(confirmed) });
        kv.push({ key: "rejected",  val: String(rejected) });
      }
      return {
        summary: `LLM cross-examined each flag — kept ${confirmed}, dismissed ${rejected}.`,
        kv,
      };
    }
    case "explanation_generator": {
      const ex = asRec(p.rule_explanations);
      const n = Object.keys(ex).length;
      kv.push({ key: "explanations", val: String(n) });
      return {
        summary: `Wrote ${n} plain-English explanation${n === 1 ? "" : "s"} with remediation notes.`,
        kv,
      };
    }
    case "violation_reporting": {
      const r = asRec(p.violation_report);
      const summ = asRec(r.summary);
      const score = Number(summ.compliance_score ?? NaN);
      const grade = String(summ.compliance_grade ?? "");
      if (!Number.isNaN(score)) kv.push({ key: "compliance score", val: score.toFixed(1) + "%" });
      if (grade) kv.push({ key: "grade", val: grade });
      return {
        summary: `Aggregated the audit — compliance ${!Number.isNaN(score) ? score.toFixed(1) + "%" : "recorded"}.`,
        kv,
      };
    }
    case "report_generation": {
      const paths = asRec(p.report_paths);
      const pdf = String(paths.pdf ?? "");
      const html = String(paths.html ?? "");
      if (pdf) kv.push({ key: "pdf", val: pdf.split(/[\\/]/).pop() || pdf });
      if (html) kv.push({ key: "html", val: html.split(/[\\/]/).pop() || html });
      return {
        summary: `PDF and HTML artifacts written to disk.`,
        kv,
      };
    }
    default:
      return null;
  }
}

// ---------- Page ------------------------------------------------------------

export default function ScanPage() {
  const [policyPath, setPolicyPath] = useState<string>(DEFAULT_PDF);
  const [dbPath, setDbPath] = useState<string>(DEFAULT_DB);
  const [uploadedName, setUploaded] = useState<string | null>(null);

  const [running, setRunning] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);

  const initialDetails = useMemo(
    () =>
      Object.fromEntries(
        PIPELINE_STAGES.map((s) => [s.id, { status: "pending" as StageStatus }]),
      ) as Record<StageId, StageDetail>,
    [],
  );
  const [details, setDetails] = useState<Record<StageId, StageDetail>>(initialDetails);

  const [hitlPayload, setHitlPayload] = useState<
    | { rules: LowConfidenceRule[]; message: string; interruptId?: string }
    | null
  >(null);

  const [runFinal, setRunFinal] = useState<RunFinalState | null>(null);

  const setStage = useCallback(
    (id: string, next: Partial<StageDetail>) => {
      setDetails((prev) => {
        const cur = (prev as Record<string, StageDetail>)[id] || { status: "pending" };
        return { ...prev, [id as StageId]: { ...cur, ...next } };
      });
    },
    [],
  );

  const onDrop = useCallback((accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setUploaded(f.name);
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

  // ---------- Run control ---------------------------------------------------

  const runScan = async () => {
    const client = getClient();
    setRunning(true);
    setDetails(initialDetails);
    setHitlPayload(null);
    setRunFinal(null);

    try {
      const thread = await client.threads.create();
      setThreadId(thread.thread_id);
      // Mark the very first stage as running; the event stream will bump the rest.
      setStage(PIPELINE_STAGES[0].id, { status: "running", at: stamp() });

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
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Run failed: ${msg}`);
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

    await finalize(client, tid);
  };

  const finalize = async (
    client: ReturnType<typeof getClient>,
    tid: string,
  ) => {
    const state = await client.threads.getState(tid);
    const values = (state.values || {}) as {
      report_paths?: { pdf?: string; html?: string };
      scan_summary?: { total_violations?: number; tables_scanned?: number };
      violation_report?: { summary?: { compliance_score?: number } };
    };
    const paths = values.report_paths || {};
    if (paths.pdf || paths.html) {
      const baseName = (p: string | undefined) =>
        p ? (p.replace(/\\/g, "/").split("/").pop() || undefined) : undefined;
      setRunFinal({
        threadId: tid,
        reportPdf: baseName(paths.pdf),
        reportHtml: baseName(paths.html),
        violations: Number(values.scan_summary?.total_violations ?? 0),
        tablesScanned: Number(values.scan_summary?.tables_scanned ?? 0),
        complianceScore:
          typeof values.violation_report?.summary?.compliance_score === "number"
            ? values.violation_report.summary.compliance_score
            : undefined,
      });
      setRunning(false);
      toast.success("Audit complete — the report is ready at the bottom of this page.");
    } else {
      toast.warning("Scan finished without a report. Check the stage stream for errors.");
      setRunning(false);
    }
  };

  const handleEvent = (evt: { event: string; data: unknown }) => {
    const { event, data } = evt;
    if (event !== "updates" || !data || typeof data !== "object") {
      if (event === "error") {
        const msg = (data as { message?: string })?.message || "stream error";
        toast.error(msg);
      }
      return;
    }

    for (const key of Object.keys(data as Record<string, unknown>)) {
      if (key === "__interrupt__") {
        const payload = (data as Record<string, unknown>)[key] as unknown;
        const first = Array.isArray(payload)
          ? (payload[0] as Record<string, unknown>)
          : (payload as Record<string, unknown>);
        const value = (first?.value as Record<string, unknown>) || first;
        setStage("human_review", { status: "waiting", at: stamp() });
        setHitlPayload({
          rules: (value?.rules as LowConfidenceRule[]) || [],
          message:
            (value?.message as string) ||
            "Low-confidence rules need your signature to proceed.",
          interruptId: (first?.interrupt_id as string) || undefined,
        });
        continue;
      }

      // A node completed — stash the summary and promote the next node to running.
      const summary = summarizeStage(key, (data as Record<string, unknown>)[key]);
      setStage(key, {
        status: "done",
        at: stamp(),
        summary: summary?.summary,
        kv: summary?.kv,
      });
      bumpNextRunning(key);
    }
  };

  const bumpNextRunning = (completedNodeId: string) => {
    const idx = PIPELINE_STAGES.findIndex((s) => s.id === completedNodeId);
    if (idx === -1 || idx === PIPELINE_STAGES.length - 1) return;
    const next = PIPELINE_STAGES[idx + 1].id;
    setDetails((prev) => {
      const cur = prev[next];
      if (cur?.status === "pending") {
        return { ...prev, [next]: { ...cur, status: "running", at: stamp() } };
      }
      return prev;
    });
  };

  const resumeHitl = async (decision: HitlDecision) => {
    if (!threadId) return;
    const client = getClient();
    setStage("human_review", { status: "done", at: stamp() });
    setHitlPayload(null);

    const stream = client.runs.stream(threadId, ASSISTANT_ID, {
      command: { resume: decision },
      streamMode: ["updates", "messages", "custom"],
      streamSubgraphs: true,
    });

    for await (const evt of stream) handleEvent(evt);
    await finalize(client, threadId);
  };

  // ---------- Derived render values ----------------------------------------

  // Active stage (first running or waiting) for the gauge label.
  const activeStage = PIPELINE_STAGES.find(
    (s) => details[s.id]?.status === "running" || details[s.id]?.status === "waiting",
  );
  const doneCount = PIPELINE_STAGES.filter((s) => details[s.id]?.status === "done").length;

  const gaugeLabel = (() => {
    if (runFinal) return "Audit complete — report below.";
    if (activeStage && details[activeStage.id]?.status === "waiting") {
      return "Waiting on your signature…";
    }
    if (activeStage) return activeStage.label;
    if (running) return "Opening the docket…";
    return "Ready. Configure the scan, then run.";
  })();

  // ---------- Render --------------------------------------------------------

  return (
    <>
      <div className="scan-shell">
        {/* LEFT: Sidebar controls */}
        <aside className="scan-aside">
          <div>
            <div className="scan-aside-kicker">Proceedings · Filed</div>
            <h1>The <em>audit</em> bench.</h1>
            <p className="scan-aside-lede">
              File your policy, name your subject, then convene the scan. Each
              stage is recorded in a trace that cannot be rewritten.
            </p>
          </div>

          <div className="scan-field">
            <span className="scan-field-label">Policy Evidence</span>
            <div
              {...getRootProps()}
              className={`scan-dropzone${isDragActive ? " is-active" : ""}`}
              aria-label="Upload policy PDF"
            >
              <input {...getInputProps()} />
              <div className="scan-dropzone-icon" aria-hidden>§</div>
              <div className="scan-dropzone-hint">
                {uploadedName
                  ? "Recorded:"
                  : isDragActive
                    ? "Drop the PDF here"
                    : "Drag a policy PDF, or click to select"}
              </div>
              {uploadedName && (
                <div className="scan-dropzone-current">{uploadedName}</div>
              )}
              <span className="scan-dropzone-default">Default · {DEFAULT_PDF}</span>
            </div>
          </div>

          <div className="scan-field">
            <span className="scan-field-label">Subject Database</span>
            <select
              value={dbPath}
              onChange={(e) => setDbPath(e.target.value)}
              className="scan-select"
              disabled={running}
            >
              <option value="data/HI-Small_Trans.db">data/HI-Small_Trans.db · AML demo</option>
            </select>
            <div className="scan-field-note">
              Keyset pagination · ~10k rows · Groq Llama 3 live.
            </div>
          </div>

          <button
            type="button"
            className="scan-run-btn"
            onClick={runScan}
            disabled={running}
          >
            <span aria-hidden>▸</span>
            {running ? "Audit in progress…" : "Convene the Audit"}
          </button>
        </aside>

        {/* RIGHT: Progress gauge + chat stream + completion */}
        <section className="scan-main">
          <ProgressGauge
            stages={PIPELINE_STAGES}
            details={details}
            label={gaugeLabel}
            doneCount={doneCount}
            running={running}
            complete={!!runFinal}
          />

          <div className="stage-stream">
            {!running && !runFinal && doneCount === 0 ? (
              <div className="stream-empty">
                <div className="stream-empty-numeral">§</div>
                <h2 className="stream-empty-title">The docket is empty.</h2>
                <p className="stream-empty-lede">
                  When you convene the audit, each of the nine stages will file
                  its findings here — one after another, in order, in plain
                  English.
                </p>
              </div>
            ) : (
              PIPELINE_STAGES.map((stage, idx) => {
                const d = details[stage.id] || { status: "pending" as StageStatus };

                // Render the HITL interjection in place of the human_review message
                // while we're awaiting decisions.
                if (stage.id === "human_review" && hitlPayload) {
                  return (
                    <HitlStream
                      key={stage.id}
                      rules={hitlPayload.rules}
                      message={hitlPayload.message}
                      onResume={resumeHitl}
                    />
                  );
                }

                return (
                  <StageMessage
                    key={stage.id}
                    index={idx}
                    numeral={ROMAN[idx]}
                    label={stage.label}
                    hint={stage.hint}
                    detail={d}
                  />
                );
              })
            )}
          </div>

          {runFinal && (
            <CompletionCard
              runFinal={runFinal}
            />
          )}
        </section>
      </div>
    </>
  );
}

// ---------- Sub-components --------------------------------------------------

function ProgressGauge({
  stages,
  details,
  label,
  doneCount,
  running,
  complete,
}: {
  stages: readonly { id: string; label: string }[];
  details: Record<StageId, StageDetail>;
  label: string;
  doneCount: number;
  running: boolean;
  complete: boolean;
}) {
  return (
    <div className="progress-gauge">
      <div className="progress-gauge-head">
        <h2 className="progress-gauge-title">
          The <em>proceedings</em>.
        </h2>
        <span className="progress-gauge-meta">
          {complete ? "Filed" : running ? "In session" : "Adjourned"}
        </span>
      </div>

      <div className="progress-gauge-numerals" aria-hidden>
        {stages.map((_, i) => {
          const d = details[stages[i].id as StageId];
          const cls =
            d?.status === "done" ? "done" :
            d?.status === "running" || d?.status === "waiting" ? "active" :
            "";
          return (
            <div key={i} className={`progress-gauge-numeral ${cls}`}>
              {ROMAN[i]}
            </div>
          );
        })}
      </div>

      <div className="progress-gauge-bars" role="progressbar"
           aria-valuemin={0} aria-valuemax={stages.length} aria-valuenow={doneCount}
           aria-label="Audit progress">
        {stages.map((s, i) => {
          const d = details[s.id as StageId];
          const cls =
            d?.status === "done" ? "done" :
            d?.status === "running" ? "active" :
            d?.status === "waiting" ? "waiting" :
            d?.status === "error" ? "error" :
            "";
          return <div key={s.id} className={`progress-bar ${cls}`} title={s.label} />;
        })}
      </div>

      <div className="progress-gauge-footer">
        <span className="progress-gauge-current">{label}</span>
        <span>{doneCount} of {stages.length} entered</span>
      </div>
    </div>
  );
}

function StageMessage({
  index,
  numeral,
  label,
  hint,
  detail,
}: {
  index: number;
  numeral: string;
  label: string;
  hint: string;
  detail: StageDetail;
}) {
  const { status } = detail;
  const statusLine = detail.summary || pendingCopy(status, hint);

  return (
    <article className={`stage-msg ${status}`} aria-label={`Stage ${index + 1}: ${label}`}>
      <div className="stage-msg-marker">
        <div className="stage-msg-numeral" aria-hidden>{numeral}</div>
        <div className="stage-msg-dot" aria-hidden />
      </div>

      <div className="stage-msg-card">
        <header className="stage-msg-header">
          <h3 className="stage-msg-title">{label}</h3>
          {detail.at && <span className="stage-msg-time">{detail.at}</span>}
        </header>
        <p className="stage-msg-status">{statusLine}</p>

        {detail.kv && detail.kv.length > 0 && (
          <div className="stage-msg-detail">
            {detail.kv.map((row) => (
              <div key={row.key} className="mono-row">
                <span className="mono-key">{row.key}</span>
                <span className="mono-val">{row.val}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

function pendingCopy(status: StageStatus, hint: string): string {
  switch (status) {
    case "running":
      return `${hint}…`;
    case "waiting":
      return "Paused — awaiting your decision.";
    case "error":
      return "Encountered an error; see the log.";
    case "done":
      return "Filed.";
    default:
      return `Not yet opened — ${hint.toLowerCase()}.`;
  }
}

function CompletionCard({ runFinal }: { runFinal: RunFinalState }) {
  const score =
    runFinal.complianceScore !== undefined
      ? `${runFinal.complianceScore.toFixed(1)}%`
      : null;

  return (
    <section className="completion-card" aria-label="Audit complete">
      <div>
        <span className="completion-kicker">Verdict Filed · MMXXVI</span>
        <h2 className="completion-title">
          The audit is <em>complete</em>.
        </h2>
        <p className="completion-lede">
          {runFinal.violations.toLocaleString()} violation
          {runFinal.violations === 1 ? "" : "s"} across {runFinal.tablesScanned} table
          {runFinal.tablesScanned === 1 ? "" : "s"}
          {score ? `, compliance ${score}` : ""} — the report is ready. Click to open it
          in the dashboard.
        </p>
      </div>

      <div>
        <Link
          href={`/dashboard/${runFinal.threadId}`}
          className="completion-btn"
        >
          Open the Dashboard
          <span className="completion-btn-arrow" aria-hidden>→</span>
        </Link>
        {(runFinal.reportPdf || runFinal.reportHtml) && (
          <a
            href={`/api/reports/${encodeURIComponent(runFinal.reportPdf || runFinal.reportHtml || "")}`}
            target="_blank"
            rel="noopener noreferrer"
            className="completion-stay"
          >
            or peek at the {runFinal.reportPdf ? "PDF" : "HTML"} directly →
          </a>
        )}
      </div>
    </section>
  );
}
