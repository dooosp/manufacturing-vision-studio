export type Locale = "en" | "ko";

export type CaseStatus =
  | "draft"
  | "ready"
  | "analyzed"
  | "disposed"
  | "exported"
  | "failed";

export type Decision = "accept" | "reject" | "needs_review" | "model_error";

export type AppSurface = "inspection" | "evaluation";

export type EvaluationProfile = "mini" | "full";

export type EvaluationVerdict = "PASS" | "HOLD";

export type EvaluationStatus = "COMPLETED" | "CALIBRATION_HOLD";

export type EvaluationGateStatus = "PASS" | "HOLD";

export type EvaluationMetricUnit =
  | "ratio"
  | "count"
  | "milliseconds"
  | "bytes"
  | "score";

export interface EvaluationGate {
  gate_id: string;
  label: string;
  status: EvaluationGateStatus;
  observed: string;
  threshold: string;
  numerator: number | null;
  denominator: number | null;
  reason: string | null;
}

export interface EvaluationMetric {
  metric_id: string;
  label: string;
  value: number | null;
  unit: EvaluationMetricUnit;
  numerator: number | null;
  denominator: number | null;
  undefined_reason: string | null;
}

export interface EvaluationSlice {
  slice_id: string;
  group_id:
    | "recall_by_severity"
    | "recall_by_defect_type"
    | "nuisance_false_positive_rate"
    | "classification_accuracy_by_revision"
    | "classification_accuracy_by_view";
  label: string;
  sample_count: number;
  metrics: EvaluationMetric[];
}

export interface EvaluationTrustCase {
  case_id: string;
  label: string;
  status: EvaluationGateStatus;
  expected_code: string;
  observed_code: string;
  published_artifact_count: number;
}

export interface EvaluationGalleryItem {
  gallery_item_id: string;
  case_id: string;
  category:
    | "false_positive"
    | "false_negative"
    | "low_dice"
    | "wrong_feature_mapping"
    | "unsupported_view"
    | "revision_mismatch"
    | "bundle_verification_failure";
  part_id: string;
  cad_revision: "rev-A" | "rev-B";
  asset_url: string;
  mask_url: string | null;
  expected_feature_id: string | null;
  predicted_feature_id: string | null;
  failure_reason: string | null;
  score: number | null;
  threshold: number;
}

export interface EvaluationBaselineIdentity {
  pipeline_id: string;
  pipeline_version: string;
  model_id: string;
  model_version: string;
  model_artifact_sha256: string;
  configuration_sha256: string;
  threshold_lock_id: string;
  threshold_lock_sha256: string;
  threshold_lock_status: "LOCKED" | "HOLD";
  locked_image_threshold: number;
  threshold_source_split: "calibration";
}

export interface E1EvaluationSnapshot {
  schema_version: string;
  protocol_id: string;
  protocol_version: string;
  protocol_sha256: string;
  dataset_id: string;
  dataset_version: string;
  dataset_manifest_sha256: string;
  result_id: string;
  evaluation_run_id: string;
  code_commit_sha: string;
  dirty_worktree: boolean;
  result_sha256: string;
  deterministic_projection_sha256: string;
  generated_at: string;
  duration_ms: number;
  evaluation_status: EvaluationStatus;
  profile: EvaluationProfile;
  case_count: number;
  inference_case_count: number;
  trust_boundary_case_count: number;
  verdict: EvaluationVerdict;
  baseline: EvaluationBaselineIdentity;
  gates: EvaluationGate[];
  metrics: EvaluationMetric[];
  slices: EvaluationSlice[];
  trust_boundary: EvaluationTrustCase[];
  gallery: EvaluationGalleryItem[];
  gallery_total: number;
  exclusions: string[];
  limitations: string[];
}

export interface ImageArtifact {
  id: string;
  filename: string;
  sha256: string;
  media_type: string;
  width: number;
  height: number;
  role: "reference" | "inspection" | "mask";
  url?: string;
}

export interface FeatureMapping {
  feature_id: string;
  label: string;
  anomaly_score: number;
  bbox?: [number, number, number, number];
}

export interface AnalysisResult {
  analysis_id: string;
  inspection_image_id: string;
  pipeline_version: string;
  model_version: string;
  configuration_hash: string;
  anomaly_score: number;
  threshold: number;
  verdict: "normal" | "anomaly" | "indeterminate" | "abstained";
  mask?: ImageArtifact;
  mask_url?: string;
  feature_mappings: FeatureMapping[];
  created_at: string;
}

export interface HumanDisposition {
  decision: Decision;
  reviewer: string;
  note: string;
  created_at: string;
}

export interface InspectionCase {
  id: string;
  case_id?: string;
  case_revision?: number;
  part_id: string;
  revision: string;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
  reference_image?: ImageArtifact | null;
  inspection_images: ImageArtifact[];
  analysis?: AnalysisResult | null;
  disposition?: HumanDisposition | null;
  limitations?: string[];
}

export interface ExportResult {
  bundle_id: string;
  bundle_sha256: string;
  manifest: Record<string, unknown>;
  download_url: string;
}

export interface VerificationResult {
  valid: boolean;
  bundle_sha256: string;
  artifact_count: number;
  errors?: string[];
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
}

export interface ApiFailure {
  detail?: string | { message?: string };
  message?: string;
}
