import type {
  Decision,
  ExportResult,
  HealthStatus,
  InspectionCase,
  VerificationResult,
} from "./types";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "/api";

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function revisionHeaders(caseRevision: number): HeadersInit {
  return { "If-Match": String(caseRevision) };
}

function normalizeImage(value: unknown): InspectionCase["inspection_images"][number] | null {
  if (!isObject(value)) return null;
  const id = asString(value.id || value.image_id);
  const role = asString(value.role) as "reference" | "inspection" | "mask";
  if (!id || !["reference", "inspection", "mask"].includes(role)) return null;
  const source = isObject(value.source) ? value.source : {};
  return {
    id,
    filename: asString(value.filename || source.original_filename, `${id}.png`),
    sha256: asString(value.sha256),
    media_type: asString(value.media_type, "image/png"),
    width: asNumber(value.width || value.width_px),
    height: asNumber(value.height || value.height_px),
    role,
    url: asString(value.url, `${API_ROOT}/images/${encodeURIComponent(id)}`),
  };
}

function normalizeCase(payload: unknown): InspectionCase {
  if (!isObject(payload)) throw new ApiError("Malformed case response", 500);
  if (typeof payload.part_id === "string" && Array.isArray(payload.inspection_images)) {
    return payload as unknown as InspectionCase;
  }

  const document = isObject(payload.case) ? payload.case : payload;
  const identity = isObject(document.part_identity) ? document.part_identity : {};
  const images = Array.isArray(payload.images)
    ? payload.images.map(normalizeImage).filter((item) => item !== null)
    : [];
  const analyses = Array.isArray(payload.analyses) ? payload.analyses.filter(isObject) : [];
  const dispositions = Array.isArray(payload.dispositions) ? payload.dispositions.filter(isObject) : [];
  const latestAnalysis = analyses.at(-1);
  const inputBinding = latestAnalysis && isObject(latestAnalysis.input_binding)
    ? latestAnalysis.input_binding
    : {};
  const completed = latestAnalysis && isObject(latestAnalysis.completed_output)
    ? latestAnalysis.completed_output
    : null;
  const pipeline = latestAnalysis && isObject(latestAnalysis.pipeline) ? latestAnalysis.pipeline : {};
  const model = latestAnalysis && isObject(latestAnalysis.model) ? latestAnalysis.model : {};
  const rawMask = completed && isObject(completed.mask) ? completed.mask : null;
  const analysisId = latestAnalysis ? asString(latestAnalysis.analysis_id) : "";
  const latestDisposition = dispositions.at(-1);
  const reviewer = latestDisposition && isObject(latestDisposition.reviewer)
    ? latestDisposition.reviewer
    : {};
  const caseId = asString(document.case_id || document.id);
  const reference = images.find((image) => image.role === "reference") ?? null;
  const inspectionImages = images.filter((image) => image.role === "inspection");

  return {
    id: caseId,
    case_id: caseId,
    case_revision: asNumber(document.case_revision, 1),
    part_id: asString(identity.part_id || document.part_id),
    revision: asString(identity.cad_revision || document.revision),
    status: asString(document.status, "draft") as InspectionCase["status"],
    created_at: asString(document.created_at),
    updated_at: asString(document.updated_at),
    reference_image: reference,
    inspection_images: inspectionImages,
    analysis: latestAnalysis && completed
      ? {
          analysis_id: analysisId,
          inspection_image_id: asString(inputBinding.inspection_image_id),
          pipeline_version: `${asString(pipeline.pipeline_id, "baseline.diff")}@${asString(pipeline.pipeline_version, "1.0.0")}`,
          model_version: `${asString(model.model_id, "deterministic-difference")}@${asString(model.model_version, "1.0.0")}`,
          configuration_hash: asString(latestAnalysis.configuration_sha256),
          anomaly_score: asNumber(completed.anomaly_score),
          threshold: asNumber(completed.threshold),
          verdict: asString(completed.automated_classification, "indeterminate") as NonNullable<InspectionCase["analysis"]>["verdict"],
          mask: rawMask
            ? {
                id: `mask-${analysisId}`,
                filename: `${analysisId}.mask.png`,
                sha256: asString(rawMask.sha256),
                media_type: asString(rawMask.media_type, "image/png"),
                width: asNumber(rawMask.width_px),
                height: asNumber(rawMask.height_px),
                role: "mask",
                url: `${API_ROOT}/analyses/${encodeURIComponent(analysisId)}/mask`,
              }
            : undefined,
          mask_url: analysisId ? `${API_ROOT}/analyses/${encodeURIComponent(analysisId)}/mask` : undefined,
          feature_mappings: Array.isArray(completed.feature_findings)
            ? completed.feature_findings.filter(isObject).map((finding) => ({
                feature_id: asString(finding.feature_id, "unmapped"),
                label: asString(finding.feature_id, "unmapped"),
                anomaly_score: asNumber(finding.anomaly_score),
              }))
            : [],
          created_at: asString(latestAnalysis.produced_at),
        }
      : null,
    disposition: latestDisposition
      ? {
          decision: asString(latestDisposition.decision, "needs_review") as NonNullable<InspectionCase["disposition"]>["decision"],
          reviewer: asString(reviewer.display_name || reviewer.reviewer_id, "Local Reviewer"),
          note: asString(latestDisposition.rationale),
          created_at: asString(latestDisposition.recorded_at),
        }
      : null,
    limitations: Array.isArray(document.limitations)
      ? document.limitations.filter((item): item is string => typeof item === "string")
      : [],
  };
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const value = payload as Record<string, unknown>;
  if (value.error && typeof value.error === "object") {
    const error = value.error as Record<string, unknown>;
    const code = typeof error.code === "string" && /^[A-Z][A-Z0-9_]{1,63}$/.test(error.code)
      ? error.code
      : null;
    const rawMessage = typeof error.message === "string" ? error.message : fallback;
    const message = safeServerMessage(rawMessage, fallback);
    return code ? `[${code}] ${message}` : message;
  }
  if (typeof value.message === "string") return safeServerMessage(value.message, fallback);
  if (typeof value.detail === "string") return safeServerMessage(value.detail, fallback);
  if (value.detail && typeof value.detail === "object") {
    const detail = value.detail as Record<string, unknown>;
    if (typeof detail.message === "string") return safeServerMessage(detail.message, fallback);
  }
  return fallback;
}

function safeServerMessage(value: string, fallback: string): string {
  return value.length <= 240
    && !/[\u0000-\u001f\u007f]/.test(value)
    && !/(?:Traceback|[A-Za-z]:\\|\/(?:Users|home|var|tmp)\/)/.test(value)
    ? value
    : fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(!(init?.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const fallback = `${response.status} ${response.statusText}`;
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(errorMessage(payload, fallback), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function unwrapCases(payload: unknown): InspectionCase[] {
  const values = Array.isArray(payload)
    ? payload
    : isObject(payload) && Array.isArray(payload.items)
      ? payload.items
      : isObject(payload) && Array.isArray(payload.cases)
        ? payload.cases
      : [];
  return values.map(normalizeCase);
}

async function fetchCase(caseId: string): Promise<InspectionCase> {
  return normalizeCase(await request<unknown>(`/cases/${encodeURIComponent(caseId)}`));
}

export const api = {
  health: () => request<HealthStatus>("/health"),

  async listCases(): Promise<InspectionCase[]> {
    return unwrapCases(await request<unknown>("/cases"));
  },

  getCase: fetchCase,

  async createCase(partId: string, revision: string) {
    return normalizeCase(await request<unknown>("/cases", {
      method: "POST",
      body: JSON.stringify({ part_id: partId, cad_revision: revision }),
    }));
  },

  async createDemo() {
    return normalizeCase(await request<unknown>("/demo", { method: "POST", body: "{}" }));
  },

  uploadReference(caseId: string, caseRevision: number, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<unknown>(`/cases/${encodeURIComponent(caseId)}/reference`, {
      method: "POST",
      body,
      headers: revisionHeaders(caseRevision),
    }).then(() => fetchCase(caseId));
  },

  uploadInspection(caseId: string, caseRevision: number, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<unknown>(`/cases/${encodeURIComponent(caseId)}/images`, {
      method: "POST",
      body,
      headers: revisionHeaders(caseRevision),
    }).then(() => fetchCase(caseId));
  },

  async analyze(caseId: string, caseRevision: number) {
    await request<unknown>(`/cases/${encodeURIComponent(caseId)}/analyze`, {
      method: "POST",
      body: "{}",
      headers: revisionHeaders(caseRevision),
    });
    return fetchCase(caseId);
  },

  disposition: (
    caseId: string,
    caseRevision: number,
    analysisId: string,
    decision: Decision,
    reviewer: string,
    note: string,
  ) =>
    request<unknown>(`/cases/${encodeURIComponent(caseId)}/disposition`, {
      method: "POST",
      body: JSON.stringify({
        analysis_id: analysisId,
        decision,
        reviewer_id: "local-reviewer",
        reviewer_display_name: reviewer,
        reason_codes: ["other"],
        rationale: note,
      }),
      headers: revisionHeaders(caseRevision),
    }).then(() => fetchCase(caseId)),

  exportEvidence: (caseId: string, caseRevision: number) =>
    request<ExportResult>(`/cases/${encodeURIComponent(caseId)}/export`, {
      method: "POST",
      body: "{}",
      headers: revisionHeaders(caseRevision),
    }),

  async verifyEvidence(downloadUrl: string) {
    const response = await fetch(downloadUrl, { headers: { Accept: "application/zip" } });
    if (!response.ok) throw new ApiError(`Evidence download failed: ${response.status}`, response.status);
    const body = new FormData();
    body.append(
      "file",
      new File([await response.blob()], "evidence-bundle.zip", { type: "application/zip" }),
    );
    return request<VerificationResult>("/evidence/verify", {
      method: "POST",
      body,
    });
  },
};
