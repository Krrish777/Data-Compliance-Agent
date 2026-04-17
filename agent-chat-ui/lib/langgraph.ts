import { Client } from "@langchain/langgraph-sdk";

export const LANGGRAPH_URL =
  process.env.NEXT_PUBLIC_LANGGRAPH_URL || "http://127.0.0.1:2024";

export const ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID || "agent";

export function getClient(): Client {
  return new Client({ apiUrl: LANGGRAPH_URL });
}

export type ComplianceState = {
  document_path?: string;
  db_type?: "sqlite" | "postgresql";
  db_config?: Record<string, unknown>;
  violations_db_path?: string;
  raw_rules?: unknown[];
  structured_rules?: unknown[];
  low_confidence_rules?: unknown[];
  schema_metadata?: Record<string, unknown>;
  scan_id?: string;
  scan_summary?: {
    total_violations?: number;
    tables_scanned?: number;
    rules_processed?: number;
    violations_by_rule?: Record<string, number>;
    violations_by_table?: Record<string, number>;
    status?: string;
  };
  validation_summary?: Record<string, unknown>;
  rule_explanations?: Record<string, unknown>;
  violation_report?: Record<string, unknown>;
  report_paths?: { pdf?: string; html?: string };
  current_stage?: string;
  errors?: string[];
};

export const PIPELINE_STAGES = [
  { id: "rule_extraction",       label: "Rule Extraction",        hint: "Reading the policy PDF" },
  { id: "schema_discovery",      label: "Schema Discovery",       hint: "Inspecting the target database" },
  { id: "rule_structuring",      label: "Rule Structuring",       hint: "Mapping rules to columns" },
  { id: "human_review",          label: "Human Review",           hint: "Waiting for your decision" },
  { id: "data_scanning",         label: "Data Scanning",          hint: "Scanning rows for violations" },
  { id: "violation_validator",   label: "Violation Validation",   hint: "Filtering false positives" },
  { id: "explanation_generator", label: "Explanation Generation", hint: "Writing audit explanations" },
  { id: "violation_reporting",   label: "Violation Reporting",    hint: "Aggregating the final report" },
  { id: "report_generation",     label: "Report Generation",      hint: "Producing PDF + HTML" },
] as const;

export type StageId = (typeof PIPELINE_STAGES)[number]["id"];
