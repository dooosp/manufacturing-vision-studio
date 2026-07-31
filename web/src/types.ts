export type Locale = "en" | "ko";

export type CaseStatus =
  | "draft"
  | "ready"
  | "analyzed"
  | "disposed"
  | "exported"
  | "failed";

export type Decision = "accept" | "reject" | "needs_review" | "model_error";

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
  bundle_path: string;
  bundle_sha256: string;
  file_count: number;
  download_url?: string;
}

export interface VerificationResult {
  valid: boolean;
  bundle_sha256: string;
  checked_files: number;
  errors: string[];
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
