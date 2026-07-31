import type {
  Decision,
  E1EvaluationSnapshot,
  EvaluationGate,
  EvaluationGalleryItem,
  EvaluationMetric,
  EvaluationProfile,
  EvaluationSlice,
  EvaluationTrustCase,
  EvaluationVerdict,
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

function malformedEvaluation(field: string): ApiError {
  return new ApiError(`Malformed E1 evaluation response: ${field}`, 500);
}

const E1_PROTOCOL_SHA256 = "140887fb9e9980c8f7854d2d9f8b0a927aee4994fb74ee2535aa109f19fa7d99";
const E1_CONFIGURATION_SHA256 = "70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0";
const E1_MODEL_ARTIFACT_SHA256 = "15d557ed44541d4e3b7f382b9b6ff6a9e510a1924b7b9d86a07c7ba52bcbbc03";
const E1_GATE_IDS = [
  "medium_high_defect_recall",
  "nuisance_only_false_positive_rate",
  "positive_case_median_dice",
  "affected_feature_mapping_accuracy",
  "revision_mismatch_publication_count",
  "corrupted_evidence_publication_count",
  "bundle_verify_reimport_rate",
  "dataset_split_hash_overlap",
  "same_seed_manifest_equivalence",
  "v0_1_regression",
] as const;
const E1_SLICE_GROUPS: EvaluationSlice["group_id"][] = [
  "recall_by_severity",
  "recall_by_defect_type",
  "nuisance_false_positive_rate",
  "classification_accuracy_by_revision",
  "classification_accuracy_by_view",
];

interface MetricEvidence {
  value: number | null;
  reason: string | null;
  numerator: number | null;
  denominator: number | null;
}

function requiredObject(value: unknown, field: string): JsonObject {
  if (!isObject(value)) throw malformedEvaluation(field);
  return value;
}

function requiredString(value: unknown, field: string): string {
  if (
    typeof value !== "string"
    || value.trim().length === 0
    || value.length > 500
    || /[\u0000-\u001f\u007f]/.test(value)
  ) {
    throw malformedEvaluation(field);
  }
  return value;
}

function requiredIdentifier(value: unknown, field: string): string {
  const identifier = requiredString(value, field);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(identifier)) {
    throw malformedEvaluation(field);
  }
  return identifier;
}

function requiredNullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return requiredString(value, field);
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw malformedEvaluation(field);
  return value;
}

function boundedNumber(value: unknown, field: string, minimum: number, maximum: number): number {
  const number = requiredNumber(value, field);
  if (number < minimum || number > maximum) throw malformedEvaluation(field);
  return number;
}

function nonNegativeInteger(value: unknown, field: string): number {
  const number = requiredNumber(value, field);
  if (!Number.isInteger(number) || number < 0) throw malformedEvaluation(field);
  return number;
}

function requiredBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw malformedEvaluation(field);
  return value;
}

function requiredSha256(value: unknown, field: string): string {
  const digest = requiredString(value, field);
  if (!/^[a-f0-9]{64}$/.test(digest)) throw malformedEvaluation(field);
  return digest;
}

function requiredGitSha(value: unknown, field: string): string {
  const digest = requiredString(value, field);
  if (!/^[a-f0-9]{40}$/.test(digest)) throw malformedEvaluation(field);
  return digest;
}

function requiredEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw malformedEvaluation(field);
  }
  return value as T;
}

function requiredArray(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw malformedEvaluation(field);
  return value;
}

function boundedArray(value: unknown, field: string, maximum: number): unknown[] {
  const entries = requiredArray(value, field);
  if (entries.length > maximum) throw malformedEvaluation(field);
  return entries;
}

function stringArray(value: unknown, field: string): string[] {
  const entries = boundedArray(value, field, 64).map((item, index) =>
    requiredString(item, `${field}.${index}`),
  );
  return [...new Set(entries)];
}

function nonEmptyStringArray(value: unknown, field: string): string[] {
  const entries = stringArray(value, field);
  if (entries.length === 0) throw malformedEvaluation(field);
  return entries;
}

function requireExact<T extends string | number>(
  value: unknown,
  expected: T,
  field: string,
): T {
  if (value !== expected) throw malformedEvaluation(field);
  return expected;
}

function validateConfidenceInterval(value: unknown, field: string, optional = false): void {
  if (optional && value === undefined) return;
  if (value === null) return;
  const interval = requiredArray(value, field);
  if (interval.length !== 2) throw malformedEvaluation(field);
  const lower = boundedNumber(interval[0], `${field}.0`, 0, 1);
  const upper = boundedNumber(interval[1], `${field}.1`, 0, 1);
  if (lower > upper) throw malformedEvaluation(field);
}

function readProportion(value: unknown, field: string): MetricEvidence {
  const metric = requiredObject(value, field);
  const normalized = {
    value: metric.value === null
      ? null
      : boundedNumber(metric.value, `${field}.value`, 0, 1),
    reason: requiredNullableString(metric.reason, `${field}.reason`),
    numerator: nonNegativeInteger(metric.numerator, `${field}.numerator`),
    denominator: nonNegativeInteger(metric.denominator, `${field}.denominator`),
  };
  validateConfidenceInterval(metric.confidence_interval, `${field}.confidence_interval`);
  if (normalized.numerator > normalized.denominator) throw malformedEvaluation(field);
  if (
    normalized.denominator === 0
      ? normalized.numerator !== 0 || normalized.value !== null
      : normalized.value === null
        || Math.abs(normalized.value - normalized.numerator / normalized.denominator) > 1e-12
  ) {
    throw malformedEvaluation(`${field}.value`);
  }
  return normalized;
}

function readScalar(value: unknown, field: string): MetricEvidence {
  const metric = requiredObject(value, field);
  validateConfidenceInterval(metric.confidence_interval, `${field}.confidence_interval`, true);
  return {
    value: metric.value === null
      ? null
      : boundedNumber(metric.value, `${field}.value`, 0, 1),
    reason: requiredNullableString(metric.reason, `${field}.reason`),
    numerator: null,
    denominator: null,
  };
}

function validateRanking(value: unknown, field: string): void {
  const metric = requiredObject(value, field);
  if (metric.value !== null) boundedNumber(metric.value, `${field}.value`, 0, 1);
  requiredNullableString(metric.reason, `${field}.reason`);
  nonNegativeInteger(metric.positive_count, `${field}.positive_count`);
  nonNegativeInteger(metric.negative_count, `${field}.negative_count`);
  validateConfidenceInterval(metric.confidence_interval, `${field}.confidence_interval`, true);
}

function toMetric(metricId: string, evidence: MetricEvidence): EvaluationMetric {
  return {
    metric_id: metricId,
    label: metricId,
    value: evidence.value,
    unit: "ratio",
    numerator: evidence.numerator,
    denominator: evidence.denominator,
    undefined_reason: evidence.reason,
  };
}

function sliceMetricId(groupId: EvaluationSlice["group_id"]): string {
  if (groupId.startsWith("recall_by_")) return "image_recall";
  if (groupId === "nuisance_false_positive_rate") {
    return "nuisance_only_false_positive_rate";
  }
  return "classification_accuracy";
}

function normalizeProportionMap(
  value: unknown,
  groupId: EvaluationSlice["group_id"],
): EvaluationSlice[] {
  const field = `metrics.slices.${groupId}`;
  const metricMap = requiredObject(value, field);
  const entries = Object.entries(metricMap);
  if (entries.length > 64) throw malformedEvaluation(field);
  return entries.map(([key, rawMetric]) => {
    requiredIdentifier(key, `${field}.key`);
    const evidence = readProportion(rawMetric, `${field}.${key}`);
    return {
      slice_id: `${groupId}:${key}`,
      group_id: groupId,
      label: key,
      sample_count: evidence.denominator ?? 0,
      metrics: [toMetric(sliceMetricId(groupId), evidence)],
    };
  });
}

function normalizeTrustSlices(value: unknown): EvaluationTrustCase[] {
  const field = "metrics.slices.trust_boundary_scenario";
  const trustMap = requiredObject(value, field);
  const entries = Object.entries(trustMap);
  if (entries.length > 24) throw malformedEvaluation(field);
  return entries.map(([scenarioId, rawCase]) => {
    requiredIdentifier(scenarioId, `${field}.key`);
    const trustCase = requiredObject(rawCase, `${field}.${scenarioId}`);
    const caseId = requiredIdentifier(trustCase.case_id, `${field}.${scenarioId}.case_id`);
    const passed = requiredBoolean(trustCase.passed, `${field}.${scenarioId}.passed`);
    requiredBoolean(trustCase.abstained, `${field}.${scenarioId}.abstained`);
    const published = requiredBoolean(trustCase.published, `${field}.${scenarioId}.published`);
    return {
      case_id: caseId,
      label: scenarioId,
      status: passed ? "PASS" : "HOLD",
      expected_code:
        requiredNullableString(
          trustCase.expected_error_code,
          `${field}.${scenarioId}.expected_error_code`,
        ) ?? "—",
      observed_code:
        requiredNullableString(
          trustCase.observed_error_code,
          `${field}.${scenarioId}.observed_error_code`,
        ) ?? "—",
      published_artifact_count: published ? 1 : 0,
    };
  });
}

function gateValue(gateId: string, value: number | boolean | null): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (
    gateId === "medium_high_defect_recall"
    || gateId === "nuisance_only_false_positive_rate"
    || gateId === "positive_case_median_dice"
    || gateId === "affected_feature_mapping_accuracy"
    || gateId === "bundle_verify_reimport_rate"
  ) {
    return `${(value * 100).toFixed(1)}%`;
  }
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
}

function normalizeGates(
  value: unknown,
  evidenceByGate: Partial<Record<(typeof E1_GATE_IDS)[number], MetricEvidence>>,
  expectedObserved: Partial<Record<(typeof E1_GATE_IDS)[number], number | boolean>>,
): EvaluationGate[] {
  const gates = requiredArray(value, "metrics.gates");
  if (gates.length !== E1_GATE_IDS.length) throw malformedEvaluation("metrics.gates");
  const seen = new Set<string>();
  const normalized = gates.map((rawGate, index) => {
    const field = `metrics.gates.${index}`;
    const gate = requiredObject(rawGate, field);
    const gateId = requiredEnum(gate.gate_id, E1_GATE_IDS, `${field}.gate_id`);
    if (seen.has(gateId)) throw malformedEvaluation(`${field}.gate_id`);
    seen.add(gateId);
    const operator = requiredEnum(
      gate.operator,
      ["gte", "lte", "eq", "is_true"] as const,
      `${field}.operator`,
    );
    const threshold = typeof gate.threshold === "boolean"
      ? gate.threshold
      : requiredNumber(gate.threshold, `${field}.threshold`);
    const observed = gate.observed === null
      ? null
      : typeof gate.observed === "boolean"
        ? gate.observed
        : requiredNumber(gate.observed, `${field}.observed`);
    const evidence = evidenceByGate[gateId];
    const expected = expectedObserved[gateId];
    if (
      expected !== undefined
      && (
        observed === null
        || typeof observed !== typeof expected
        || (typeof observed === "number" && typeof expected === "number"
          ? Math.abs(observed - expected) > 1e-12
          : observed !== expected)
      )
    ) {
      throw malformedEvaluation(`${field}.observed`);
    }
    let computedPassed: boolean;
    if (observed === null) {
      computedPassed = false;
    } else if (operator === "gte" || operator === "lte") {
      if (typeof observed !== "number" || typeof threshold !== "number") {
        throw malformedEvaluation(field);
      }
      computedPassed = operator === "gte" ? observed >= threshold : observed <= threshold;
    } else if (operator === "eq") {
      if (typeof observed !== typeof threshold) throw malformedEvaluation(field);
      computedPassed = observed === threshold;
    } else {
      if (typeof observed !== "boolean" || threshold !== true) throw malformedEvaluation(field);
      computedPassed = observed;
    }
    const declaredPassed = requiredBoolean(gate.passed, `${field}.passed`);
    if (declaredPassed !== computedPassed) throw malformedEvaluation(`${field}.passed`);
    const operatorLabel = { gte: "≥", lte: "≤", eq: "=", is_true: "=" }[operator];
    return {
      gate_id: gateId,
      label: requiredString(gate.scope, `${field}.scope`),
      status: computedPassed ? "PASS" : "HOLD",
      observed: gateValue(gateId, observed),
      threshold: `${operatorLabel} ${gateValue(gateId, threshold)}`,
      numerator: evidence?.numerator ?? null,
      denominator: evidence?.denominator ?? null,
      reason: requiredNullableString(gate.reason, `${field}.reason`),
    } satisfies EvaluationGate;
  });
  if (seen.size !== E1_GATE_IDS.length) throw malformedEvaluation("metrics.gates");
  return normalized;
}

function validatePixelDistribution(value: unknown): void {
  boundedArray(value, "metrics.pixel_level.positive_case_distribution", 120).forEach(
    (rawCase, index) => {
      const field = `metrics.pixel_level.positive_case_distribution.${index}`;
      const pixelCase = requiredObject(rawCase, field);
      requiredIdentifier(pixelCase.case_id, `${field}.case_id`);
      if (pixelCase.defect_type !== null) {
        requiredEnum(
          pixelCase.defect_type,
          ["scratch", "stain", "edge_chip", "burr", "blocked_hole", "hole_geometry_deviation"] as const,
          `${field}.defect_type`,
        );
      }
      if (pixelCase.severity !== null) {
        requiredEnum(pixelCase.severity, ["LOW", "MEDIUM", "HIGH"] as const, `${field}.severity`);
      }
      boundedNumber(pixelCase.iou, `${field}.iou`, 0, 1);
      boundedNumber(pixelCase.dice, `${field}.dice`, 0, 1);
      nonNegativeInteger(pixelCase.truth_positive_pixels, `${field}.truth_positive_pixels`);
      nonNegativeInteger(pixelCase.predicted_positive_pixels, `${field}.predicted_positive_pixels`);
      nonNegativeInteger(pixelCase.intersection_pixels, `${field}.intersection_pixels`);
    },
  );
}

function normalizeMetrics(value: unknown, verdict: EvaluationVerdict): Pick<
  E1EvaluationSnapshot,
  "gates" | "metrics" | "slices" | "trust_boundary"
> {
  const metrics = requiredObject(value, "metrics");
  requireExact(metrics.evaluation_split, "test", "metrics.evaluation_split");
  requireExact(metrics.verdict, verdict, "metrics.verdict");

  const image = requiredObject(metrics.image_level, "metrics.image_level");
  const confusion = requiredObject(image.confusion, "metrics.image_level.confusion");
  const confusionCounts = ["true_positive", "true_negative", "false_positive", "false_negative"]
    .map((key) => nonNegativeInteger(confusion[key], `metrics.image_level.confusion.${key}`));
  const sampleCount = nonNegativeInteger(confusion.sample_count, "metrics.image_level.confusion.sample_count");
  if (confusionCounts.reduce((sum, count) => sum + count, 0) !== sampleCount) {
    throw malformedEvaluation("metrics.image_level.confusion.sample_count");
  }
  const imagePrecision = readProportion(image.precision, "metrics.image_level.precision");
  const imageRecall = readProportion(image.recall, "metrics.image_level.recall");
  readProportion(image.specificity, "metrics.image_level.specificity");
  readScalar(image.f1, "metrics.image_level.f1");
  validateRanking(image.average_precision, "metrics.image_level.average_precision");
  validateRanking(image.auroc, "metrics.image_level.auroc");
  const coverage = requiredObject(image.score_coverage, "metrics.image_level.score_coverage");
  const scored = nonNegativeInteger(coverage.scored, "metrics.image_level.score_coverage.scored");
  const total = nonNegativeInteger(coverage.total, "metrics.image_level.score_coverage.total");
  const excluded = nonNegativeInteger(coverage.excluded, "metrics.image_level.score_coverage.excluded");
  if (scored + excluded !== total) throw malformedEvaluation("metrics.image_level.score_coverage");
  const nuisanceRate = readProportion(
    image.nuisance_only_false_positive_rate,
    "metrics.image_level.nuisance_only_false_positive_rate",
  );

  const pixel = requiredObject(metrics.pixel_level, "metrics.pixel_level");
  const medianDice = readScalar(
    pixel.positive_case_median_dice,
    "metrics.pixel_level.positive_case_median_dice",
  );
  readScalar(pixel.positive_case_median_iou, "metrics.pixel_level.positive_case_median_iou");
  const maskPrecision = readProportion(pixel.mask_precision, "metrics.pixel_level.mask_precision");
  const maskRecall = readProportion(pixel.mask_recall, "metrics.pixel_level.mask_recall");
  readProportion(pixel.empty_mask_accuracy, "metrics.pixel_level.empty_mask_accuracy");
  validatePixelDistribution(pixel.positive_case_distribution);

  const engineering = requiredObject(metrics.engineering_level, "metrics.engineering_level");
  const featureMapping = readProportion(
    engineering.affected_feature_mapping_accuracy,
    "metrics.engineering_level.affected_feature_mapping_accuracy",
  );
  readProportion(engineering.part_binding_accuracy, "metrics.engineering_level.part_binding_accuracy");
  readProportion(
    engineering.revision_binding_accuracy,
    "metrics.engineering_level.revision_binding_accuracy",
  );
  const abstention = readProportion(
    engineering.abstention_correctness,
    "metrics.engineering_level.abstention_correctness",
  );

  const trust = requiredObject(metrics.trust_boundary, "metrics.trust_boundary");
  const revisionMismatchPublications = nonNegativeInteger(
    trust.revision_mismatch_publication_count,
    "metrics.trust_boundary.revision_mismatch_publication_count",
  );
  const corruptedEvidencePublications = nonNegativeInteger(
    trust.corrupted_evidence_publication_count,
    "metrics.trust_boundary.corrupted_evidence_publication_count",
  );
  const reimportRate = readProportion(
    trust.bundle_verify_reimport_rate,
    "metrics.trust_boundary.bundle_verify_reimport_rate",
  );
  const splitHashOverlap = nonNegativeInteger(
    trust.dataset_split_hash_overlap,
    "metrics.trust_boundary.dataset_split_hash_overlap",
  );
  const sameSeedEquivalent = requiredBoolean(
    trust.same_seed_manifest_equivalence,
    "metrics.trust_boundary.same_seed_manifest_equivalence",
  );
  const v01Regression = requiredBoolean(
    trust.v0_1_regression,
    "metrics.trust_boundary.v0_1_regression",
  );

  const slicesObject = requiredObject(metrics.slices, "metrics.slices");
  const slices = E1_SLICE_GROUPS.flatMap((groupId) =>
    normalizeProportionMap(slicesObject[groupId], groupId),
  );
  const trustBoundary = normalizeTrustSlices(slicesObject.trust_boundary_scenario);
  const mediumHighMetrics = slices
    .filter(
      (slice) => slice.group_id === "recall_by_severity"
        && ["MEDIUM", "HIGH"].includes(slice.label.toUpperCase()),
    )
    .map((slice) => slice.metrics[0])
    .filter((metric): metric is EvaluationMetric => Boolean(metric));
  const mediumHighNumerator = mediumHighMetrics.reduce(
    (sum, metric) => sum + (metric.numerator ?? 0),
    0,
  );
  const mediumHighDenominator = mediumHighMetrics.reduce(
    (sum, metric) => sum + (metric.denominator ?? 0),
    0,
  );
  const mediumHighRecall: MetricEvidence = mediumHighMetrics.length > 0
    ? {
        value: mediumHighDenominator > 0 ? mediumHighNumerator / mediumHighDenominator : null,
        reason: mediumHighDenominator > 0 ? null : "No medium/high severity cases.",
        numerator: mediumHighNumerator,
        denominator: mediumHighDenominator,
      }
    : { value: null, reason: "No medium/high severity slices.", numerator: null, denominator: null };
  const evidenceByGate = {
    medium_high_defect_recall: mediumHighRecall,
    nuisance_only_false_positive_rate: nuisanceRate,
    positive_case_median_dice: medianDice,
    affected_feature_mapping_accuracy: featureMapping,
    bundle_verify_reimport_rate: reimportRate,
  };
  const expectedObserved = {
    medium_high_defect_recall: mediumHighRecall.value ?? undefined,
    nuisance_only_false_positive_rate: nuisanceRate.value ?? undefined,
    positive_case_median_dice: medianDice.value ?? undefined,
    affected_feature_mapping_accuracy: featureMapping.value ?? undefined,
    revision_mismatch_publication_count: revisionMismatchPublications,
    corrupted_evidence_publication_count: corruptedEvidencePublications,
    bundle_verify_reimport_rate: reimportRate.value ?? undefined,
    dataset_split_hash_overlap: splitHashOverlap,
    same_seed_manifest_equivalence: sameSeedEquivalent,
    v0_1_regression: v01Regression,
  };
  const gates = normalizeGates(metrics.gates, evidenceByGate, expectedObserved);
  const gateSummary = requiredObject(metrics.gate_summary, "metrics.gate_summary");
  const passed = nonNegativeInteger(gateSummary.passed, "metrics.gate_summary.passed");
  requireExact(gateSummary.total, 10, "metrics.gate_summary.total");
  const allPassed = requiredBoolean(gateSummary.all_passed, "metrics.gate_summary.all_passed");
  const actualPassed = gates.filter((gate) => gate.status === "PASS").length;
  if (
    passed !== actualPassed
    || allPassed !== (actualPassed === 10)
    || (verdict === "PASS") !== allPassed
  ) {
    throw malformedEvaluation("metrics.gate_summary");
  }

  return {
    gates,
    metrics: [
      toMetric("image_precision", imagePrecision),
      toMetric("image_recall", imageRecall),
      toMetric("nuisance_only_false_positive_rate", nuisanceRate),
      toMetric("positive_case_median_dice", medianDice),
      toMetric("mask_precision", maskPrecision),
      toMetric("mask_recall", maskRecall),
      toMetric("affected_feature_mapping_accuracy", featureMapping),
      toMetric("abstention_correctness", abstention),
    ],
    slices,
    trust_boundary: trustBoundary,
  };
}

function normalizeAssetUrl(value: unknown, field: string): string {
  const path = requiredString(value, field);
  if (!/^\/api\/v1\/e1\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$/.test(path)) {
    throw malformedEvaluation(field);
  }
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(path);
  } catch {
    throw malformedEvaluation(field);
  }
  const decodedSegments = decodedPath.split("/");
  if (decodedSegments.some((segment) => segment === "." || segment === "..")) {
    throw malformedEvaluation(field);
  }
  const canonicalPath = new URL(path, "https://mvs.invalid").pathname;
  if (canonicalPath !== path || !canonicalPath.startsWith("/api/v1/e1/")) {
    throw malformedEvaluation(field);
  }
  return path;
}

function normalizeNullableAssetUrl(value: unknown, field: string): string | null {
  return value === null ? null : normalizeAssetUrl(value, field);
}

function normalizeGalleryItem(value: unknown, index: number): EvaluationGalleryItem | null {
  const field = `error_gallery.${index}`;
  const item = requiredObject(value, field);
  const caseId = requiredIdentifier(item.case_id, `${field}.case_id`);
  const identity = requiredObject(item.part_identity, `${field}.part_identity`);
  requireExact(identity.part_id, "MVS-E1-PLATE-001", `${field}.part_identity.part_id`);
  const revision = requiredEnum(identity.cad_revision, ["rev-A", "rev-B"] as const, `${field}.part_identity.cad_revision`);
  const sourceHashes = requiredObject(item.source_hashes, `${field}.source_hashes`);
  requiredSha256(sourceHashes.reference_sha256, `${field}.source_hashes.reference_sha256`);
  requiredSha256(sourceHashes.inspection_sha256, `${field}.source_hashes.inspection_sha256`);
  requiredSha256(
    sourceHashes.authoritative_mask_sha256,
    `${field}.source_hashes.authoritative_mask_sha256`,
  );
  if (sourceHashes.predicted_mask_sha256 !== null) {
    requiredSha256(
      sourceHashes.predicted_mask_sha256,
      `${field}.source_hashes.predicted_mask_sha256`,
    );
  }
  const assets = requiredObject(item.assets, `${field}.assets`);
  const referenceUrl = normalizeNullableAssetUrl(
    assets.reference_image_url,
    `${field}.assets.reference_image_url`,
  );
  const inspectionUrl = normalizeNullableAssetUrl(
    assets.inspection_image_url,
    `${field}.assets.inspection_image_url`,
  );
  const authoritativeMaskUrl = normalizeNullableAssetUrl(
    assets.authoritative_mask_url,
    `${field}.assets.authoritative_mask_url`,
  );
  const predictedMaskUrl = normalizeNullableAssetUrl(
    assets.predicted_mask_url,
    `${field}.assets.predicted_mask_url`,
  );
  const overlayUrl = normalizeNullableAssetUrl(assets.overlay_url, `${field}.assets.overlay_url`);
  const assetUrl = overlayUrl ?? inspectionUrl ?? referenceUrl;
  if (!assetUrl) return null;
  return {
    gallery_item_id: `${caseId}:${index}`,
    case_id: caseId,
    category: requiredEnum(
      item.category,
      [
        "false_positive",
        "false_negative",
        "low_dice",
        "wrong_feature_mapping",
        "unsupported_view",
        "revision_mismatch",
        "bundle_verification_failure",
      ] as const,
      `${field}.category`,
    ),
    part_id: "MVS-E1-PLATE-001",
    cad_revision: revision,
    asset_url: assetUrl,
    mask_url: overlayUrl ? null : predictedMaskUrl ?? authoritativeMaskUrl,
    expected_feature_id: requiredNullableString(
      item.expected_feature_id,
      `${field}.expected_feature_id`,
    ),
    predicted_feature_id: requiredNullableString(
      item.predicted_feature_id,
      `${field}.predicted_feature_id`,
    ),
    failure_reason: requiredNullableString(item.failure_reason, `${field}.failure_reason`),
    score: item.score === null
      ? null
      : boundedNumber(item.score, `${field}.score`, 0, 1),
    threshold: requireExact(item.threshold, 0.0025, `${field}.threshold`),
  };
}

function validateReproducibility(value: unknown): boolean {
  const reproducibility = requiredObject(value, "reproducibility");
  requireExact(reproducibility.repeat_count, 2, "reproducibility.repeat_count");
  const equivalent = requiredBoolean(reproducibility.equivalent, "reproducibility.equivalent");
  const projections = requiredArray(
    reproducibility.deterministic_projection_sha256s,
    "reproducibility.deterministic_projection_sha256s",
  );
  if (projections.length !== 2) {
    throw malformedEvaluation("reproducibility.deterministic_projection_sha256s");
  }
  projections.forEach((digest, index) =>
    requiredSha256(digest, `reproducibility.deterministic_projection_sha256s.${index}`),
  );
  const volatileFields = requiredArray(
    reproducibility.volatile_fields_excluded,
    "reproducibility.volatile_fields_excluded",
  );
  const expected = ["duration_ms", "evaluation_run_id", "generated_at", "local_absolute_paths"];
  if (volatileFields.length !== expected.length || volatileFields.some((item, index) => item !== expected[index])) {
    throw malformedEvaluation("reproducibility.volatile_fields_excluded");
  }
  return equivalent;
}

function normalizeEvaluation(
  payload: unknown,
  requestedProfile: EvaluationProfile,
): E1EvaluationSnapshot | null {
  if (payload === null || payload === undefined) return null;
  const evaluation = requiredObject(payload, "$");
  requireExact(evaluation.schema_version, "1.0.0", "schema_version");
  const profile = requiredEnum<EvaluationProfile>(
    evaluation.profile,
    ["mini", "full"],
    "profile",
  );
  if (profile !== requestedProfile) throw malformedEvaluation("profile");
  const evaluationStatus = requiredEnum(
    evaluation.evaluation_status,
    ["COMPLETED", "CALIBRATION_HOLD"] as const,
    "evaluation_status",
  );
  const verdict = requiredEnum<EvaluationVerdict>(
    evaluation.verdict,
    ["PASS", "HOLD"],
    "verdict",
  );
  if (evaluationStatus === "CALIBRATION_HOLD" && verdict !== "HOLD") {
    throw malformedEvaluation("verdict");
  }
  const protocol = requiredObject(evaluation.protocol, "protocol");
  requireExact(protocol.protocol_id, "mvs-e1", "protocol.protocol_id");
  requireExact(protocol.protocol_version, "1.3.0", "protocol.protocol_version");
  requireExact(protocol.protocol_sha256, E1_PROTOCOL_SHA256, "protocol.protocol_sha256");
  const code = requiredObject(evaluation.code, "code");
  const generator = requiredObject(evaluation.generator, "generator");
  requireExact(generator.generator_id, "mvs-e1-generator", "generator.generator_id");
  requireExact(generator.generator_version, "1.0.0", "generator.generator_version");
  requiredSha256(
    generator.generator_configuration_sha256,
    "generator.generator_configuration_sha256",
  );
  const dataset = requiredObject(evaluation.dataset, "dataset");
  requireExact(dataset.dataset_version, "1.0.0", "dataset.dataset_version");
  const caseCount = nonNegativeInteger(dataset.case_count, "dataset.case_count");
  const inferenceCaseCount = nonNegativeInteger(
    dataset.inference_case_count,
    "dataset.inference_case_count",
  );
  const trustBoundaryCaseCount = nonNegativeInteger(dataset.trust_case_count, "dataset.trust_case_count");
  const expectedCounts = profile === "mini"
    ? { cases: 48, inference: 44, trust: 4 }
    : { cases: 480, inference: 456, trust: 24 };
  if (
    caseCount !== expectedCounts.cases
    || inferenceCaseCount !== expectedCounts.inference
    || trustBoundaryCaseCount !== expectedCounts.trust
  ) {
    throw malformedEvaluation("profile counts");
  }
  const pipeline = requiredObject(evaluation.pipeline, "pipeline");
  requireExact(pipeline.pipeline_id, "e1-normalized-local-difference", "pipeline.pipeline_id");
  requireExact(pipeline.pipeline_version, "1.1.0", "pipeline.pipeline_version");
  const model = requiredObject(evaluation.model, "model");
  requireExact(model.model_id, "e1-normalized-local-difference", "model.model_id");
  requireExact(model.model_version, "1.1.0", "model.model_version");
  requireExact(
    model.model_artifact_sha256,
    E1_MODEL_ARTIFACT_SHA256,
    "model.model_artifact_sha256",
  );
  requireExact(evaluation.configuration_sha256, E1_CONFIGURATION_SHA256, "configuration_sha256");
  const threshold = requiredObject(evaluation.threshold, "threshold");
  const thresholdLockStatus = requiredEnum(
    threshold.lock_status,
    ["LOCKED", "HOLD"] as const,
    "threshold.lock_status",
  );
  if (
    (evaluationStatus === "COMPLETED" && thresholdLockStatus !== "LOCKED")
    || (evaluationStatus === "CALIBRATION_HOLD" && thresholdLockStatus !== "HOLD")
  ) {
    throw malformedEvaluation("threshold.lock_status");
  }
  const execution = requiredObject(evaluation.execution_environment, "execution_environment");
  requireExact(execution.runtime_id, "python-numpy", "execution_environment.runtime_id");
  requiredString(execution.python_version, "execution_environment.python_version");
  requiredString(execution.numpy_version, "execution_environment.numpy_version");
  requiredString(execution.pillow_version, "execution_environment.pillow_version");
  requiredString(execution.platform, "execution_environment.platform");
  if ("local_absolute_paths" in evaluation) {
    throw malformedEvaluation("local_absolute_paths");
  }
  const reproducibilityEquivalent = validateReproducibility(evaluation.reproducibility);
  const rawGallery = boundedArray(evaluation.error_gallery, "error_gallery", 12);
  const gallery = rawGallery
    .map(normalizeGalleryItem)
    .filter((item): item is EvaluationGalleryItem => item !== null);
  const metrics = evaluation.metrics === null
    ? { gates: [], metrics: [], slices: [], trust_boundary: [] }
    : normalizeMetrics(evaluation.metrics, verdict);
  if (evaluation.metrics !== null) {
    const rawMetrics = requiredObject(evaluation.metrics, "metrics");
    const rawTrust = requiredObject(rawMetrics.trust_boundary, "metrics.trust_boundary");
    const sameSeedEquivalent = requiredBoolean(
      rawTrust.same_seed_manifest_equivalence,
      "metrics.trust_boundary.same_seed_manifest_equivalence",
    );
    if (
      reproducibilityEquivalent !== sameSeedEquivalent
      || (verdict === "PASS" && !reproducibilityEquivalent)
    ) {
      throw malformedEvaluation("reproducibility.equivalent");
    }
  }
  if (
    (evaluationStatus === "COMPLETED" && evaluation.metrics === null)
    || (evaluationStatus === "CALIBRATION_HOLD" && evaluation.metrics !== null)
  ) {
    throw malformedEvaluation("metrics");
  }

  return {
    schema_version: "1.0.0",
    protocol_id: "mvs-e1",
    protocol_version: "1.3.0",
    protocol_sha256: E1_PROTOCOL_SHA256,
    dataset_id: requiredIdentifier(dataset.dataset_id, "dataset.dataset_id"),
    dataset_version: "1.0.0",
    dataset_manifest_sha256: requiredSha256(
      dataset.dataset_manifest_sha256,
      "dataset.dataset_manifest_sha256",
    ),
    result_id: requiredIdentifier(evaluation.result_id, "result_id"),
    evaluation_run_id: requiredIdentifier(evaluation.evaluation_run_id, "evaluation_run_id"),
    code_commit_sha: requiredGitSha(code.code_commit_sha, "code.code_commit_sha"),
    dirty_worktree: requiredBoolean(code.dirty_worktree, "code.dirty_worktree"),
    result_sha256: requiredSha256(evaluation.result_sha256, "result_sha256"),
    deterministic_projection_sha256: requiredSha256(
      evaluation.deterministic_projection_sha256,
      "deterministic_projection_sha256",
    ),
    generated_at: requiredString(evaluation.generated_at, "generated_at"),
    duration_ms: nonNegativeInteger(evaluation.duration_ms, "duration_ms"),
    evaluation_status: evaluationStatus,
    profile,
    case_count: caseCount,
    inference_case_count: inferenceCaseCount,
    trust_boundary_case_count: trustBoundaryCaseCount,
    verdict,
    baseline: {
      pipeline_id: "e1-normalized-local-difference",
      pipeline_version: "1.1.0",
      model_id: "e1-normalized-local-difference",
      model_version: "1.1.0",
      model_artifact_sha256: E1_MODEL_ARTIFACT_SHA256,
      configuration_sha256: E1_CONFIGURATION_SHA256,
      threshold_lock_id: requiredIdentifier(threshold.lock_id, "threshold.lock_id"),
      threshold_lock_sha256: requiredSha256(
        threshold.threshold_lock_sha256,
        "threshold.threshold_lock_sha256",
      ),
      threshold_lock_status: thresholdLockStatus,
      locked_image_threshold: requireExact(
        threshold.locked_image_threshold,
        0.0025,
        "threshold.locked_image_threshold",
      ),
      threshold_source_split: requireExact(
        threshold.threshold_source_split,
        "calibration",
        "threshold.threshold_source_split",
      ),
    },
    ...metrics,
    gallery,
    gallery_total: rawGallery.length,
    exclusions: nonEmptyStringArray(evaluation.exclusions, "exclusions"),
    limitations: nonEmptyStringArray(evaluation.limitations, "limitations"),
  };
}

export const api = {
  health: () => request<HealthStatus>("/health"),

  async listCases(): Promise<InspectionCase[]> {
    return unwrapCases(await request<unknown>("/cases"));
  },

  getCase: fetchCase,

  async getLatestEvaluation(profile: EvaluationProfile): Promise<E1EvaluationSnapshot | null> {
    return normalizeEvaluation(
      await request<unknown>(`/v1/e1/evaluation/latest?profile=${encodeURIComponent(profile)}`),
      profile,
    );
  },

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
