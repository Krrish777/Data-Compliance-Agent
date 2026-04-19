"use client";
import { useEffect, useState, use as usePromise } from "react";
import Link from "next/link";
import { FileDown, ArrowLeft } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

import { getClient, type ComplianceState } from "@/lib/langgraph";
import { ScoreGauge } from "@/components/ScoreGauge";
import { ViolationsTable, type ViolationRow } from "@/components/ViolationsTable";

type RuleExplanation = {
  rule_text?: string;
  rule_type?: string;
  violation_count?: number;
  severity?: string;
  explanation?: string;
  policy_clause?: string;
};

export default function DashboardPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}) {
  const { threadId } = usePromise(params);
  const [state, setState] = useState<ComplianceState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const client = getClient();
        const res = await client.threads.getState(threadId);
        if (!cancelled) setState(res.values as ComplianceState);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [threadId]);

  if (err) {
    return (
      <div className="py-20">
        <div className="caps-label text-accent-red">Error</div>
        <h1 className="display-lg text-3xl mb-4">Could not load thread {threadId}</h1>
        <pre className="font-mono text-xs bg-cream-deep p-4 rounded-sm">{err}</pre>
        <Link href="/scan" className="text-sm mt-6 inline-flex items-center gap-1 hover:text-teal-deep">
          <ArrowLeft className="w-4 h-4" /> Back to scanner
        </Link>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="py-20">
        <div className="caps-label">Loading audit…</div>
        <div className="mt-6 space-y-4">
          <div className="h-56 bg-cream-deep rounded-sm animate-pulse" />
          <div className="h-72 bg-cream-deep rounded-sm animate-pulse" />
        </div>
      </div>
    );
  }

  const summary = state.scan_summary || {};
  const explanations = (state.rule_explanations || {}) as Record<string, RuleExplanation>;
  const totalViolations = summary.total_violations || 0;

  // Compliance score: 100 - penalty weighted by severity. Conservative heuristic.
  const { score, grade } = scoreFromExplanations(explanations);

  const byRule = Object.entries(summary.violations_by_rule || {}).map(
    ([rule_id, count]) => ({ name: rule_id, count }),
  );
  const byType = aggregateByType(explanations);

  const rows: ViolationRow[] = Object.entries(explanations).map(([rule_id, e]) => ({
    rule_id,
    rule_type: e.rule_type,
    violation_count: e.violation_count || 0,
    severity: e.severity,
    explanation: e.explanation,
  }));

  // Backend emits absolute or mixed-separator paths (e.g. "data\compliance_report_xxx.pdf"
  // on Windows). The /api/reports route only trusts files inside data/, so send just the
  // basename and let the route resolve it there.
  const baseName = (p: string | undefined): string | undefined =>
    p ? p.replace(/\\/g, "/").split("/").pop() || undefined : undefined;
  const reportPdf = baseName(state.report_paths?.pdf);
  const reportHtml = baseName(state.report_paths?.html);

  return (
    <div>
      <div className="flex items-start justify-between mb-8">
        <div>
          <div className="caps-label mb-1">Audit Session · {threadId.slice(0, 12)}…</div>
          <h1 className="display-lg text-4xl">Compliance Report</h1>
          <div className="text-sm text-ink-secondary mt-1">
            {totalViolations.toLocaleString()} violations flagged across {summary.tables_scanned || 0} tables
          </div>
        </div>
        <div className="flex gap-2">
          {reportPdf && (
            <a
              href={`/api/reports/${encodeURIComponent(reportPdf)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 border border-ink px-4 py-2 rounded-sm text-sm hover:bg-ink hover:text-cream"
            >
              <FileDown className="w-4 h-4" /> PDF
            </a>
          )}
          {reportHtml && (
            <a
              href={`/api/reports/${encodeURIComponent(reportHtml)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 border border-ink px-4 py-2 rounded-sm text-sm hover:bg-ink hover:text-cream"
            >
              <FileDown className="w-4 h-4" /> HTML
            </a>
          )}
          {!reportPdf && !reportHtml && (
            <span className="text-xs text-ink-muted italic border border-dashed border-border-dark px-3 py-2 rounded-sm">
              Report artifact not found. Check server logs.
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-8 mb-8">
        <ScoreGauge score={score} grade={grade} />

        <div className="bg-card border border-border p-6 rounded-sm">
          <div className="caps-label mb-4">Violations by Rule Type</div>
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={byType} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip cursor={{ fill: "var(--teal-wash)" }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {byType.map((_, i) => (
                    <Cell key={i} fill="var(--teal-deep)" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {byRule.length > 0 && (
        <div className="bg-card border border-border p-6 rounded-sm mb-8">
          <div className="caps-label mb-4">Violations by Rule</div>
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={byRule} layout="vertical" margin={{ top: 10, right: 20, left: 30, bottom: 0 }}>
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={120} />
                <Tooltip cursor={{ fill: "var(--teal-wash)" }} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {byRule.map((_, i) => (
                    <Cell key={i} fill="var(--teal-mid)" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <ViolationsTable rows={rows} />

      <div className="mt-8">
        <Link href="/scan" className="inline-flex items-center gap-1 text-sm hover:text-teal-deep">
          <ArrowLeft className="w-4 h-4" /> Run another audit
        </Link>
      </div>
    </div>
  );
}

function scoreFromExplanations(
  explanations: Record<string, RuleExplanation>,
): { score: number; grade: string } {
  let penalty = 0;
  for (const e of Object.values(explanations)) {
    const weight = e.severity === "HIGH" ? 8 : e.severity === "MEDIUM" ? 3 : 1;
    penalty += Math.min(weight * (e.violation_count || 0) ** 0.5, 25);
  }
  const score = Math.max(0, Math.min(100, Math.round(100 - penalty)));
  const grade =
    score >= 90 ? "A" :
    score >= 80 ? "B" :
    score >= 70 ? "C" :
    score >= 60 ? "D" : "F";
  return { score, grade };
}

function aggregateByType(
  explanations: Record<string, RuleExplanation>,
): { name: string; count: number }[] {
  const totals: Record<string, number> = {};
  for (const e of Object.values(explanations)) {
    const t = e.rule_type || "unknown";
    totals[t] = (totals[t] || 0) + (e.violation_count || 0);
  }
  return Object.entries(totals)
    .map(([name, count]) => ({ name: name.replace("data_", ""), count }))
    .sort((a, b) => b.count - a.count);
}
