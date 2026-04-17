import Link from "next/link";

export default function Home() {
  return (
    <div className="py-10">
      <div className="caps-label mb-4">Est. 2026 · Volume 1</div>
      <h1 className="display-xl text-[clamp(2.5rem,5vw,3.125rem)] mb-6 max-w-3xl">
        Regulatory compliance, <em className="italic">witnessed</em> by an agent that reads the rulebook.
      </h1>
      <p className="text-lg text-ink-secondary max-w-2xl mb-10 leading-relaxed">
        AuditLens reads your policy PDFs, extracts enforceable rules, scans your
        transactional database, and produces an audit-ready report with
        explanations and remediation steps — all in one end-to-end pipeline.
      </p>

      <div className="flex items-center gap-4 mb-16">
        <Link
          href="/scan"
          className="inline-flex items-center justify-center bg-teal-deep text-cream px-8 py-4 rounded-sm font-sans text-sm tracking-wider uppercase hover:bg-teal-mid transition-colors"
        >
          Begin Audit →
        </Link>
        <Link
          href="#pipeline"
          className="inline-flex items-center justify-center border border-ink text-ink px-8 py-4 rounded-sm font-sans text-sm tracking-wider uppercase hover:bg-ink hover:text-cream transition-colors"
        >
          View the Pipeline
        </Link>
      </div>

      <section id="pipeline" className="pt-16">
        <div className="rule-double mb-6" />
        <div className="caps-label mb-4">The Pipeline</div>
        <h2 className="display-lg text-3xl mb-8 max-w-3xl">Nine stages, one state contract, one report.</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            ["I",   "Rule Extraction",        "LLM reads the policy PDF and extracts structured rules with confidence scores."],
            ["II",  "Schema Discovery",       "Connects to SQLite/Postgres, discovers columns, primary keys, and sensitive PII."],
            ["III", "Rule Structuring",       "Maps extracted rules to real column names and normalises operators (40+ aliases)."],
            ["IV",  "Human Review",           "Low-confidence rules pause the graph for explicit approve / edit / drop."],
            ["V",   "Data Scanning",          "Keyset-paginated scan; no OFFSET bottlenecks on million-row tables."],
            ["VI",  "Violation Validation",   "LLM classifies each flagged record as confirmed or false positive."],
            ["VII", "Explanation Generation", "LLM writes plain-English remediation steps, policy clauses, risk notes."],
            ["VIII","Violation Reporting",    "Aggregate the audit report with compliance score and grade."],
            ["IX",  "Report Generation",      "Produce the final PDF + HTML audit artifact."],
          ].map(([n, t, d]) => (
            <div key={t} className="bg-card border border-border p-6 rounded-sm">
              <div className="caps-label mb-3">Stage {n}</div>
              <div className="font-display text-xl mb-2">{t}</div>
              <div className="text-sm text-ink-secondary leading-relaxed">{d}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
