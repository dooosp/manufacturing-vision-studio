import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

const SHA = {
  protocol: "140887fb9e9980c8f7854d2d9f8b0a927aee4994fb74ee2535aa109f19fa7d99",
  dataset: "2".repeat(64),
  result: "3".repeat(64),
  generator: "4".repeat(64),
  threshold: "5".repeat(64),
  projection: "6".repeat(64),
  sourceReference: "8".repeat(64),
  sourceInspection: "9".repeat(64),
  sourceTruth: "a".repeat(64),
  sourcePrediction: "b".repeat(64),
};

const CONFIGURATION_SHA = "70400090ee420f42470e1b8c539f1145e5a71620ceb57d32b7cf6823ffd8ade0";
const MODEL_ARTIFACT_SHA = "15d557ed44541d4e3b7f382b9b6ff6a9e510a1924b7b9d86a07c7ba52bcbbc03";

const gateDefinitions = [
  ["medium_high_defect_recall", "severity:MEDIUM,HIGH", "gte", 0.95, 1],
  ["nuisance_only_false_positive_rate", "nuisance-only", "lte", 0.02, 0],
  ["positive_case_median_dice", "positive cases", "gte", 0.85, 0.92],
  ["affected_feature_mapping_accuracy", "affected features", "gte", 0.95, 1],
  ["revision_mismatch_publication_count", "revision mismatch", "eq", 0, 0],
  ["corrupted_evidence_publication_count", "corrupted evidence", "eq", 0, 0],
  ["bundle_verify_reimport_rate", "bundle verify/re-import", "eq", 1, 1],
  ["dataset_split_hash_overlap", "dataset split", "eq", 0, 0],
  ["same_seed_manifest_equivalence", "same seed", "is_true", true, true],
  ["v0_1_regression", "v0.1", "is_true", true, true],
] as const;

function proportion(value: number | null, numerator: number, denominator: number) {
  return {
    value,
    reason: value === null ? "Both classes are required." : null,
    numerator,
    denominator,
    confidence_interval: value === null ? null : [value, value],
  };
}

function scalar(value: number | null) {
  return { value, reason: value === null ? "No positive cases." : null, confidence_interval: null };
}

function ranking(value: number, positiveCount: number, negativeCount: number) {
  return {
    value,
    reason: null,
    positive_count: positiveCount,
    negative_count: negativeCount,
    confidence_interval: null,
  };
}

const PIXEL_INTERSECTION = 92;
const PIXEL_TRUTH = 100;
const PIXEL_PREDICTED = 100;
const PIXEL_DICE = (2 * PIXEL_INTERSECTION) / (PIXEL_TRUTH + PIXEL_PREDICTED);
const PIXEL_IOU = PIXEL_INTERSECTION / (PIXEL_TRUTH + PIXEL_PREDICTED - PIXEL_INTERSECTION);

function positiveCaseDistribution() {
  const defectTypes = [
    "scratch",
    "stain",
    "edge_chip",
    "burr",
    "blocked_hole",
    "hole_geometry_deviation",
  ] as const;
  const severities = ["LOW", "MEDIUM", "HIGH"] as const;
  return Array.from({ length: 12 }, (_, index) => ({
    case_id: `e1-positive-${String(index + 1).padStart(2, "0")}`,
    defect_type: defectTypes[index % defectTypes.length],
    severity: severities[index % severities.length],
    dice: PIXEL_DICE,
    iou: PIXEL_IOU,
    truth_positive_pixels: PIXEL_TRUTH,
    predicted_positive_pixels: PIXEL_PREDICTED,
    intersection_pixels: PIXEL_INTERSECTION,
  }));
}

function evaluationResult(profile: "mini" | "full") {
  const counts = profile === "mini"
    ? { total: 48, inference: 44, trust: 4 }
    : { total: 480, inference: 456, trust: 24 };
  const gates = gateDefinitions.map(([gateId, scope, operator, threshold, observed]) => ({
    gate_id: gateId,
    scope,
    operator,
    threshold,
    observed,
    passed: true,
    reason: null,
  }));

  return {
    schema_version: "1.0.0",
    result_id: `e1-${profile}-result-20260731`,
    evaluation_run_id: `e1-${profile}-run-20260731`,
    generated_at: "2026-07-31T12:30:00Z",
    duration_ms: 4200,
    evaluation_status: "COMPLETED",
    profile,
    protocol: {
      protocol_id: "mvs-e1",
      protocol_version: "1.3.0",
      protocol_sha256: SHA.protocol,
    },
    code: { code_commit_sha: "c".repeat(40), dirty_worktree: false },
    generator: {
      generator_id: "mvs-e1-generator",
      generator_version: "1.0.0",
      generator_configuration_sha256: SHA.generator,
    },
    dataset: {
      dataset_id: `mvs-e1-${profile}`,
      dataset_version: "1.0.0",
      dataset_manifest_sha256: SHA.dataset,
      case_count: counts.total,
      inference_case_count: counts.inference,
      trust_case_count: counts.trust,
    },
    pipeline: {
      pipeline_id: "e1-normalized-local-difference",
      pipeline_version: "1.1.0",
    },
    model: {
      model_id: "e1-normalized-local-difference",
      model_version: "1.1.0",
      model_artifact_sha256: MODEL_ARTIFACT_SHA,
    },
    configuration_sha256: CONFIGURATION_SHA,
    threshold: {
      lock_id: "e1-calibration-lock",
      threshold_lock_sha256: SHA.threshold,
      lock_status: "LOCKED",
      locked_image_threshold: 0.0025,
      threshold_source_split: "calibration",
    },
    execution_environment: {
      runtime_id: "python-numpy",
      python_version: "3.13.5",
      numpy_version: "2.3.1",
      pillow_version: "11.3.0",
      platform: "darwin-arm64",
    },
    metrics: {
      evaluation_split: "test",
      image_level: {
        confusion: {
          true_positive: 12,
          true_negative: 20,
          false_positive: 0,
          false_negative: 0,
          sample_count: 32,
        },
        precision: proportion(1, 12, 12),
        recall: proportion(1, 12, 12),
        specificity: proportion(1, 20, 20),
        f1: scalar(1),
        average_precision: ranking(1, 12, 20),
        auroc: ranking(1, 12, 20),
        score_coverage: { scored: counts.inference, total: counts.inference, excluded: 0 },
        nuisance_only_false_positive_rate: proportion(0, 0, 6),
      },
      pixel_level: {
        positive_case_median_dice: scalar(PIXEL_DICE),
        positive_case_median_iou: scalar(PIXEL_IOU),
        mask_precision: proportion(PIXEL_DICE, 12 * PIXEL_INTERSECTION, 12 * PIXEL_PREDICTED),
        mask_recall: proportion(PIXEL_DICE, 12 * PIXEL_INTERSECTION, 12 * PIXEL_TRUTH),
        empty_mask_accuracy: proportion(1, 20, 20),
        positive_case_distribution: positiveCaseDistribution(),
      },
      engineering_level: {
        affected_feature_mapping_accuracy: proportion(1, 12, 12),
        part_binding_accuracy: proportion(1, counts.inference, counts.inference),
        revision_binding_accuracy: proportion(1, counts.inference, counts.inference),
        abstention_correctness: proportion(1, counts.trust, counts.trust),
      },
      trust_boundary: {
        revision_mismatch_publication_count: 0,
        corrupted_evidence_publication_count: 0,
        bundle_verify_reimport_rate: proportion(1, counts.trust, counts.trust),
        dataset_split_hash_overlap: 0,
        same_seed_manifest_equivalence: true,
        v0_1_regression: true,
      },
      slices: {
        recall_by_severity: {
          MEDIUM: proportion(1, 6, 6),
          HIGH: proportion(1, 6, 6),
        },
        recall_by_defect_type: { scratch: proportion(1, 4, 4) },
        nuisance_false_positive_rate: { translation: proportion(0, 0, 6) },
        classification_accuracy_by_revision: {
          "rev-A": proportion(1, 16, 16),
          "rev-B": proportion(1, 16, 16),
        },
        classification_accuracy_by_view: { top: proportion(1, 32, 32) },
        trust_boundary_scenario: {
          revision_mismatch: {
            case_id: "trust-revision-mismatch",
            expected_error_code: "REVISION_MISMATCH",
            observed_error_code: "REVISION_MISMATCH",
            abstained: true,
            published: false,
            passed: true,
          },
          corrupted_evidence: {
            case_id: "trust-corrupt-evidence",
            expected_error_code: "HASH_MISMATCH",
            observed_error_code: "HASH_MISMATCH",
            abstained: true,
            published: false,
            passed: true,
          },
        },
      },
      gates,
      gate_summary: { passed: 10, total: 10, all_passed: true },
      verdict: "PASS",
    },
    reproducibility: {
      repeat_count: 2,
      equivalent: true,
      deterministic_projection_sha256s: [SHA.projection, SHA.projection],
      volatile_fields_excluded: [
        "duration_ms",
        "evaluation_run_id",
        "generated_at",
        "local_absolute_paths",
      ],
    },
    error_gallery: Array.from({ length: 9 }, (_, index) => {
      const trustCase = index === 0;
      const caseId = `e1-case-${String(index + 1).padStart(2, "0")}`;
      const assetRoot = `/api/v1/e1/evaluation/assets/${profile}/${caseId}`;
      return {
        case_id: caseId,
        category: trustCase
          ? "revision_mismatch"
          : index % 2 === 0 ? "low_dice" : "wrong_feature_mapping",
        part_identity: {
          part_id: "MVS-E1-PLATE-001",
          cad_revision: index % 2 === 0 ? "rev-A" : "rev-B",
        },
        score: trustCase ? null : index % 2 === 0 ? 0.042 : 0.0004,
        threshold: 0.0025,
        expected_feature_id: trustCase ? null : "top_face",
        predicted_feature_id: trustCase ? null : index % 2 === 0 ? "top_face" : "edge_feature",
        failure_reason: trustCase
          ? "REVISION_MISMATCH"
          : index % 2 === 0 ? "Dice below review target." : "Feature binding differs.",
        source_hashes: {
          reference_sha256: SHA.sourceReference,
          inspection_sha256: SHA.sourceInspection,
          authoritative_mask_sha256: SHA.sourceTruth,
          predicted_mask_sha256: trustCase ? null : SHA.sourcePrediction,
        },
        assets: {
          reference_image_url: `${assetRoot}/reference.png`,
          inspection_image_url: `${assetRoot}/inspection.png`,
          authoritative_mask_url: `${assetRoot}/authoritative-mask.png`,
          predicted_mask_url: trustCase
            ? null
            : `${assetRoot}/predicted-mask.png`,
          overlay_url: trustCase ? null : `${assetRoot}/overlay.png`,
        },
      };
    }),
    exclusions: ["No real camera imagery is in scope."],
    limitations: [
      "Synthetic evidence only; no field-performance claim is permitted.",
      "The mini profile is a deterministic CI subset of the full profile.",
    ],
    deterministic_projection_sha256: SHA.projection,
    result_sha256: SHA.result,
    verdict: "PASS",
  };
}

function calibrationHoldResult() {
  const completed = evaluationResult("mini");
  return {
    ...completed,
    evaluation_status: "CALIBRATION_HOLD",
    threshold: { ...completed.threshold, lock_status: "HOLD" },
    metrics: null,
    error_gallery: [],
    verdict: "HOLD",
  };
}

async function fulfillGallery(route: Route): Promise<void> {
  const label = new URL(route.request().url()).pathname.split("/").at(-1) ?? "fixture";
  await route.fulfill({
    status: 200,
    contentType: "image/svg+xml",
    body: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="#111b24"/><path d="M80 90h240v120H80z" fill="#26343f" stroke="#3de0cf" stroke-width="3"/><text x="200" y="265" text-anchor="middle" fill="#a9b7bf" font-size="18">${label}</text></svg>`,
  });
}

async function installApiMocks(
  page: Page,
  latest: (route: Route, call: number, profile: string | null) => Promise<void>,
) {
  let latestCalls = 0;
  const e1Methods: string[] = [];
  const writeRequests: string[] = [];
  const requestedProfiles: Array<string | null> = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const pathname = requestUrl.pathname;
    if (pathname.includes("/e1/")) e1Methods.push(request.method());
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      writeRequests.push(`${request.method()} ${pathname}`);
    }

    if (pathname === "/api/health") {
      await route.fulfill({ json: { status: "ok", service: "mvs", version: "test" } });
      return;
    }
    if (pathname === "/api/cases" && request.method() === "GET") {
      await route.fulfill({ json: [] });
      return;
    }
    if (pathname === "/api/v1/e1/evaluation/latest") {
      latestCalls += 1;
      const profile = requestUrl.searchParams.get("profile");
      requestedProfiles.push(profile);
      await latest(route, latestCalls, profile);
      return;
    }
    if (pathname.startsWith("/api/v1/e1/evaluation/assets/")) {
      await fulfillGallery(route);
      return;
    }
    await route.fulfill({ status: 404, json: { detail: "Mock route not found" } });
  });

  return {
    getLatestCalls: () => latestCalls,
    getE1Methods: () => [...e1Methods],
    getWriteRequests: () => [...writeRequests],
    getRequestedProfiles: () => [...requestedProfiles],
  };
}

test("renders the read-only E1 evidence surface with semantic, bounded evidence", async ({
  page,
}, testInfo) => {
  const mocks = await installApiMocks(page, async (route, _call, profile) => {
    await route.fulfill({ json: evaluationResult(profile === "full" ? "full" : "mini") });
  });

  await page.goto("/");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();

  const evaluationTab = page.getByRole("tab", { name: "E1 Evaluation" });
  await evaluationTab.focus();
  await page.keyboard.press("Enter");

  await expect(evaluationTab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Synthetic robustness evaluation" })).toBeVisible();
  await expect(page.getByText("SYNTHETIC ONLY · NOT FIELD_READY", { exact: true })).toBeVisible();
  await expect(page.getByText("48 / 48 profile cases", { exact: true })).toBeVisible();
  await expect(page.getByText("480", { exact: true })).toBeVisible();
  await expect(page.getByText("PASS", { exact: true }).first()).toBeVisible();

  const gateTable = page.getByRole("table", { name: "E1 acceptance gate results" });
  await expect(gateTable.locator("tbody tr")).toHaveCount(10);
  await expect(gateTable.getByRole("row", { name: /Medium\/high defect recall/ })).toContainText("12 / 12");

  const confusionTable = page.getByRole("table", { name: "E1 held-out image confusion matrix" });
  await expect(confusionTable.getByLabel("True positive (TP): 12")).toBeVisible();
  await expect(confusionTable.getByLabel("True negative (TN): 20")).toBeVisible();
  await expect(confusionTable.getByLabel("False positive (FP): 0")).toBeVisible();
  await expect(confusionTable.getByLabel("False negative (FN): 0")).toBeVisible();
  await expect(confusionTable.locator("tfoot tr")).toContainText("32");

  const distributionTable = page.getByRole("table", {
    name: "E1 positive-case Dice and IoU distribution",
  });
  await expect(distributionTable.locator("tbody tr")).toHaveCount(12);
  await expect(distributionTable.getByRole("row", { name: /e1-positive-01/ })).toContainText("0.9200");
  await expect(distributionTable.getByRole("row", { name: /e1-positive-01/ })).toContainText("0.8519");
  await expect(page.getByText("Showing all 12 positive cases", { exact: true })).toBeVisible();

  const sliceTable = page.getByRole("table", { name: "E1 metric results by evaluation slice" });
  await expect(sliceTable.getByText("Recall by severity · MEDIUM", { exact: true })).toBeVisible();
  const trustTable = page.getByRole("table", { name: "E1 trust-boundary results" });
  await expect(trustTable.getByRole("row", { name: /Revision mismatch/ })).toContainText("0");

  await expect(page.locator(".evaluation-gallery figure")).toHaveCount(8);
  await expect(page.getByText("Showing 8 of 9 gallery items", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Error explorer" })).toBeVisible();
  const trustGalleryCase = page.locator(".evaluation-gallery figure").first();
  await expect(trustGalleryCase.locator("img")).toHaveCount(3);
  await expect(trustGalleryCase.locator(".evaluation-gallery-asset-missing")).toHaveCount(2);
  await expect(trustGalleryCase).toContainText(SHA.sourceReference);
  await expect(trustGalleryCase).toContainText(SHA.sourceInspection);
  await expect(trustGalleryCase).toContainText(SHA.sourceTruth);
  await expect(trustGalleryCase).toContainText("REVISION_MISMATCH");
  await expect(page.locator('img[src="null"], img[src="undefined"], img[src=""]')).toHaveCount(0);
  const fullyVisualGalleryCase = page.locator(".evaluation-gallery figure").nth(1);
  const fullyVisualAssets = fullyVisualGalleryCase.locator("img");
  await expect(fullyVisualAssets).toHaveCount(5);
  await fullyVisualAssets.last().scrollIntoViewIfNeeded();
  await expect.poll(() => fullyVisualAssets.evaluateAll((images) =>
    images.every((image) => image.complete && image.naturalWidth > 0),
  )).toBe(true);
  await expect(fullyVisualGalleryCase).toContainText(SHA.sourcePrediction);
  await expect(fullyVisualGalleryCase).toContainText("0.0004");
  await expect(fullyVisualGalleryCase).toContainText("0.0025");
  const firstGalleryImage = page.locator(".evaluation-gallery img").first();
  await firstGalleryImage.scrollIntoViewIfNeeded();
  await expect(firstGalleryImage).toHaveJSProperty("complete", true);
  expect(await firstGalleryImage.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByText("make evaluate-e1-mini", { exact: true })).toBeVisible();
  await expect(page.getByText("make evaluate-e1-full", { exact: true })).toBeVisible();
  await expect(page.getByText("make verify-e1-results", { exact: true })).toBeVisible();
  expect(mocks.getLatestCalls()).toBe(1);
  expect(mocks.getRequestedProfiles()).toEqual(["mini"]);
  expect(mocks.getE1Methods()).not.toContain("POST");
  expect(mocks.getWriteRequests()).toEqual([]);

  await page.getByRole("button", { name: /Full.*480.*cases/ }).click();
  await expect(page.getByText("480 / 480 profile cases", { exact: true })).toBeVisible();
  expect(mocks.getRequestedProfiles()).toEqual(["mini", "full"]);

  const screenshotPath = testInfo.outputPath("e1-evaluation-workspace.png");
  await page.screenshot({ fullPage: true, path: screenshotPath });
  await testInfo.attach("e1-evaluation-workspace", {
    path: screenshotPath,
    contentType: "image/png",
  });

  await evaluationTab.focus();
  await page.keyboard.press("ArrowLeft");
  const inspectionTab = page.getByRole("tab", { name: "Inspection" });
  await expect(inspectionTab).toBeFocused();
  await expect(inspectionTab).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(evaluationTab).toBeFocused();
  await expect(page.getByRole("heading", { name: "Synthetic robustness evaluation" })).toBeVisible();
  expect(mocks.getLatestCalls()).toBe(2);

  await page.getByRole("button", { name: "한국어" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(page.getByText("합성 데이터 전용 · NOT FIELD_READY", { exact: true })).toBeVisible();
  const koreanGateTable = page.getByRole("table", { name: "E1 수락 게이트 결과" });
  await expect(koreanGateTable).toBeVisible();
  await expect(koreanGateTable.getByText("중간/높음 결함 재현율", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "E1 보류 이미지 혼동행렬" })).toBeVisible();
  await expect(page.getByRole("table", { name: "E1 양성 케이스 Dice 및 IoU 분포" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "오류 탐색기" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "정확한 재현 명령" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "합성 강건성 평가" })).toBeVisible();
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
});

test("surfaces loading, safe error, and empty states without issuing evaluation writes", async ({
  page,
}) => {
  let releaseFirstResponse: (() => void) | undefined;
  const firstResponseGate = new Promise<void>((resolve) => {
    releaseFirstResponse = resolve;
  });
  const mocks = await installApiMocks(page, async (route, call) => {
    if (call === 1) {
      await firstResponseGate;
      await route.fulfill({
        status: 503,
        json: {
          error: {
            code: "E1_RESULT_UNAVAILABLE",
            message: "Latest validated E1 result is unavailable.",
          },
        },
      });
      return;
    }
    await route.fulfill({
      status: 404,
      json: { error: { code: "E1_RESULT_NOT_FOUND", message: "No validated result for mini." } },
    });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();
  await expect(page.getByRole("heading", { name: "Loading the latest E1 snapshot" })).toBeVisible();
  releaseFirstResponse?.();
  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("[E1_RESULT_UNAVAILABLE]");

  await page.getByRole("button", { name: "Retry read" }).click();
  await expect(page.getByRole("heading", { name: "No E1 evaluation has been published" })).toBeVisible();
  await expect(page.getByText("SYNTHETIC ONLY · NOT FIELD_READY", { exact: true })).toBeVisible();
  expect(mocks.getLatestCalls()).toBe(2);
  expect(mocks.getE1Methods()).not.toContain("POST");
  expect(mocks.getWriteRequests()).toEqual([]);
});

test("renders calibration HOLD without inventing zero-valued test metrics", async ({ page }) => {
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: calibrationHoldResult() });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByText("HOLD", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(
    "Calibration stopped on HOLD before test gates were evaluated; no synthetic zero values are shown.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByText(
    "Calibration stopped on HOLD before test metrics were evaluated; no synthetic zero values are shown.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByRole("table", { name: "E1 acceptance gate results" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "E1 held-out image confusion matrix" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "E1 positive-case Dice and IoU distribution" })).toHaveCount(0);
  await expect(page.getByText("make verify-e1-results", { exact: true })).toBeVisible();
  expect(mocks.getRequestedProfiles()).toEqual(["mini"]);
  expect(mocks.getE1Methods()).not.toContain("POST");
  expect(mocks.getWriteRequests()).toEqual([]);
});

test("rejects an error-gallery URL that escapes the E1 asset namespace", async ({ page }) => {
  const escapedResult = evaluationResult("mini");
  escapedResult.error_gallery[0]!.assets.overlay_url =
    "/api/v1/e1/evaluation/assets/mini/e1-case-01/%2e%2e/%2e%2e/health";
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: escapedResult });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Malformed E1 evaluation response: error_gallery.0.assets.overlay_url",
  );
  expect(mocks.getE1Methods()).toEqual(["GET"]);
});

test("rejects an absolute error-gallery asset URL", async ({ page }) => {
  const escapedResult = evaluationResult("mini");
  escapedResult.error_gallery[1]!.assets.reference_image_url = "https://example.invalid/reference.png";
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: escapedResult });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Malformed E1 evaluation response: error_gallery.1.assets.reference_image_url",
  );
  expect(mocks.getE1Methods()).toEqual(["GET"]);
});

test("rejects a predicted-mask URL without its source hash", async ({ page }) => {
  const malformedResult = evaluationResult("mini");
  malformedResult.error_gallery[0]!.assets.predicted_mask_url =
    "/api/v1/e1/evaluation/assets/mini/e1-case-01/predicted-mask.png";
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: malformedResult });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Malformed E1 evaluation response: error_gallery.0.assets.predicted_mask_url",
  );
  expect(mocks.getE1Methods()).toEqual(["GET"]);
});

test("rejects an in-namespace URL that is not the declared asset route", async ({ page }) => {
  const malformedResult = evaluationResult("mini");
  malformedResult.error_gallery[1]!.assets.reference_image_url =
    "/api/v1/e1/gallery/e1-case-02/reference.png";
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: malformedResult });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Malformed E1 evaluation response: error_gallery.1.assets.reference_image_url",
  );
  expect(mocks.getE1Methods()).toEqual(["GET"]);
});

const REQUIRED_GALLERY_ASSETS = [
  "reference_image_url",
  "inspection_image_url",
  "authoritative_mask_url",
] as const;

for (const assetField of REQUIRED_GALLERY_ASSETS) {
  test(`rejects a missing core gallery asset: ${assetField}`, async ({ page }) => {
    const malformedResult = evaluationResult("mini");
    const assets: Record<(typeof REQUIRED_GALLERY_ASSETS)[number], string | null> =
      malformedResult.error_gallery[1]!.assets;
    assets[assetField] = null;
    const mocks = await installApiMocks(page, async (route) => {
      await route.fulfill({ json: malformedResult });
    });

    await page.goto("/");
    await page.getByRole("tab", { name: "E1 Evaluation" }).click();

    await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      `Malformed E1 evaluation response: error_gallery.1.assets.${assetField}`,
    );
    expect(mocks.getE1Methods()).toEqual(["GET"]);
  });
}

test("rejects a Dice value that disagrees with the retained pixel evidence", async ({ page }) => {
  const malformedResult = evaluationResult("mini");
  malformedResult.metrics.pixel_level.positive_case_distribution[0]!.dice = 0.99;
  const mocks = await installApiMocks(page, async (route) => {
    await route.fulfill({ json: malformedResult });
  });

  await page.goto("/");
  await page.getByRole("tab", { name: "E1 Evaluation" }).click();

  await expect(page.getByRole("heading", { name: "Evaluation evidence is unavailable" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Malformed E1 evaluation response: metrics.pixel_level.positive_case_distribution.0.dice",
  );
  expect(mocks.getE1Methods()).toEqual(["GET"]);
});
