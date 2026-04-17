"use client";
import { useMemo, useState } from "react";

export type ViolationRow = {
  rule_id: string;
  rule_type?: string;
  violation_count: number;
  severity?: string;
  explanation?: string;
  table?: string;
};

export function ViolationsTable({ rows }: { rows: ViolationRow[] }) {
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<keyof ViolationRow>("violation_count");

  const filtered = useMemo(() => {
    const f = filter.toLowerCase().trim();
    const matches = rows.filter(
      (r) =>
        !f ||
        r.rule_id.toLowerCase().includes(f) ||
        (r.rule_type || "").toLowerCase().includes(f) ||
        (r.severity || "").toLowerCase().includes(f) ||
        (r.explanation || "").toLowerCase().includes(f),
    );
    return [...matches].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return bv - av;
      return String(bv || "").localeCompare(String(av || ""));
    });
  }, [rows, filter, sortKey]);

  return (
    <div className="bg-card border border-border rounded-sm">
      <div className="p-4 border-b border-border flex items-center justify-between gap-4">
        <div className="caps-label">Violations by Rule</div>
        <input
          placeholder="Filter by rule, severity, text…"
          className="text-sm border border-border-dark px-3 py-1.5 rounded-sm bg-cream focus:outline-none focus:border-teal-deep"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs caps-label border-b border-border">
            {[
              { key: "rule_id",         label: "Rule" },
              { key: "rule_type",       label: "Type" },
              { key: "severity",        label: "Severity" },
              { key: "violation_count", label: "Count" },
            ].map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 cursor-pointer hover:text-teal-deep"
                onClick={() => setSortKey(col.key as keyof ViolationRow)}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr>
              <td colSpan={4} className="px-4 py-10 text-center text-ink-muted text-sm">
                No violations to show.
              </td>
            </tr>
          ) : (
            filtered.map((r) => (
              <tr key={r.rule_id} className="border-b border-border last:border-b-0 hover:bg-teal-wash">
                <td className="px-4 py-3 font-mono text-xs">{r.rule_id}</td>
                <td className="px-4 py-3 text-ink-secondary">{r.rule_type || "—"}</td>
                <td className="px-4 py-3">
                  <SeverityPill s={r.severity} />
                </td>
                <td className="px-4 py-3 font-mono tabular-nums">
                  {r.violation_count.toLocaleString()}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function SeverityPill({ s }: { s?: string }) {
  const color =
    s === "HIGH"   ? "bg-accent-red text-white"   :
    s === "MEDIUM" ? "bg-accent-amber text-white" :
    s === "LOW"    ? "bg-teal-wash text-teal-deep" :
                     "bg-cream-deep text-ink-muted";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-sm text-[10px] uppercase tracking-wider ${color}`}>
      {s || "—"}
    </span>
  );
}
