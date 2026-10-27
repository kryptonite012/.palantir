export interface User {
  id: string;
  username: string;
  display_name: string;
  global_role: string | null;
  global_role_label?: string | null;
  is_active: boolean;
  mfa_enabled: boolean;
  global_permissions?: string[];
  projects?: { project_id: string; role: string }[];
}

export interface Project {
  id: string;
  name: string;
  description: string;
  classification: string;
  role: string | null;
  role_label?: string;
  permissions?: string[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  message: string;
  result: Record<string, unknown> & { dataset?: { id: string; name: string; version: number } };
  error: string | null;
  attempts: number;
  created_at: string;
  finished_at: string | null;
  project_id: string | null;
}

export interface SchemaField { name: string; type: string; source: string; sensitive: boolean; required: boolean }

export interface Dataset {
  id: string;
  name: string;
  description: string;
  access_policy: string;
  retention_policy: string;
  current_version: number;
  is_synthetic: boolean;
  created_at: string;
  latest: null | {
    version_id: string;
    version: number;
    record_count: number;
    imported_at: string;
    schema: { fields: SchemaField[] };
    quality: QualitySummary;
    content_sha256: string;
    origin: string;
  };
}

export interface QualitySummary {
  rows?: number;
  rows_with_errors?: number;
  issue_counts?: Record<string, number>;
  completeness?: Record<string, number | null>;
  schema_drift?: { added?: string[]; removed?: string[]; type_changed?: string[] };
  duplicate_rows?: number;
}

export interface EntityView {
  id: string;
  entity_type: string;
  display_name: string;
  status: string;
  merged_into_id: string | null;
  attributes: Record<string, unknown[]>;
  redacted_fields: string[];
  relationship_count?: number;
}

export interface GraphNode { id: string; label: string; entity_type: string; degree?: number | null; hops?: number }
export interface GraphEdge {
  id: string; source: string; target: string; rel_type: string; assertion: string; assertion_label: string;
  status: string; confidence: number | null; evidence_count: number;
}

export interface AnalysisRun {
  id: string; kind: string; params: Record<string, unknown>; inputs: Record<string, unknown>;
  algorithm_version: string; software_version: string; result_sha256: string; duration_ms: number;
  reproduced_from_id: string | null; created_at: string; result?: any;
}

export interface Citation {
  n: number; document_id: string; title: string; page: number; page_label: string; chunk_id: string; excerpt: string;
  injection_warning: boolean;
}
