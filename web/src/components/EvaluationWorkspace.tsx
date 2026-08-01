import type { Copy } from "../copy";
import type {
  E1EvaluationSnapshot,
  EvaluationGateStatus,
  EvaluationGalleryItem,
  EvaluationMetric,
  EvaluationProfile,
  EvaluationSlice,
  Locale,
} from "../types";

export type EvaluationLoadState = "idle" | "loading" | "ready" | "empty" | "error";

interface EvaluationWorkspaceProps {
  copy: Copy;
  locale: Locale;
  snapshot: E1EvaluationSnapshot | null;
  profile: EvaluationProfile;
  state: EvaluationLoadState;
  error: string | null;
  onRefresh: () => Promise<void>;
  onProfileChange: (profile: EvaluationProfile) => Promise<void>;
}

const PROFILE_CASE_COUNTS = {
  mini: 48,
  full: 480,
} as const;

const GALLERY_LIMIT = 8;
const REPRODUCTION_COMMANDS = [
  "make evaluate-e1-mini",
  "make evaluate-e1-full",
  "make verify-e1-results",
] as const;

function formatDate(value: string, locale: Locale): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
}

function formatMetricValue(metric: EvaluationMetric): string {
  if (metric.value === null) return "—";
  if (metric.unit === "ratio") return `${(metric.value * 100).toFixed(1)}%`;
  if (metric.unit === "milliseconds") return `${metric.value.toFixed(1)} ms`;
  if (metric.unit === "bytes") return `${Math.round(metric.value).toLocaleString()} B`;
  if (metric.unit === "count") return Math.round(metric.value).toLocaleString();
  return metric.value.toFixed(4);
}

function formatEvidenceCount(numerator: number | null, denominator: number | null): string {
  if (numerator === null || denominator === null) return "—";
  return `${numerator.toLocaleString()} / ${denominator.toLocaleString()}`;
}

function formatIdentifierLabel(value: string): string {
  const label = value.replaceAll("_", " ");
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}`;
}

function gateLabel(copy: Copy, gateId: string, fallback: string): string {
  const labels: Record<string, string> = {
    medium_high_defect_recall: copy.evaluation.gateLabels.mediumHighDefectRecall,
    nuisance_only_false_positive_rate: copy.evaluation.gateLabels.nuisanceOnlyFalsePositiveRate,
    positive_case_median_dice: copy.evaluation.gateLabels.positiveCaseMedianDice,
    affected_feature_mapping_accuracy: copy.evaluation.gateLabels.affectedFeatureMappingAccuracy,
    revision_mismatch_publication_count:
      copy.evaluation.gateLabels.revisionMismatchPublicationCount,
    corrupted_evidence_publication_count:
      copy.evaluation.gateLabels.corruptedEvidencePublicationCount,
    bundle_verify_reimport_rate: copy.evaluation.gateLabels.bundleVerifyReimportRate,
    dataset_split_hash_overlap: copy.evaluation.gateLabels.datasetSplitHashOverlap,
    same_seed_manifest_equivalence: copy.evaluation.gateLabels.sameSeedManifestEquivalence,
    v0_1_regression: copy.evaluation.gateLabels.v01Regression,
  };
  return labels[gateId] ?? fallback;
}

function metricLabel(copy: Copy, metricId: string, fallback: string): string {
  const labels: Record<string, string> = {
    image_precision: copy.evaluation.metricLabels.imagePrecision,
    image_recall: copy.evaluation.metricLabels.imageRecall,
    mask_precision: copy.evaluation.metricLabels.maskPrecision,
    mask_recall: copy.evaluation.metricLabels.maskRecall,
    abstention_correctness: copy.evaluation.metricLabels.abstentionCorrectness,
    classification_accuracy: copy.evaluation.metricLabels.classificationAccuracy,
  };
  return labels[metricId] ?? gateLabel(copy, metricId, fallback);
}

function sliceLabel(copy: Copy, slice: EvaluationSlice): string {
  const labels: Record<EvaluationSlice["group_id"], string> = {
    recall_by_severity: copy.evaluation.sliceLabels.recallBySeverity,
    recall_by_defect_type: copy.evaluation.sliceLabels.recallByDefectType,
    nuisance_false_positive_rate: copy.evaluation.sliceLabels.nuisanceFalsePositiveRate,
    classification_accuracy_by_revision: copy.evaluation.sliceLabels.classificationByRevision,
    classification_accuracy_by_view: copy.evaluation.sliceLabels.classificationByView,
  };
  return `${labels[slice.group_id]} · ${slice.label}`;
}

function StatusBadge({ status }: { status: EvaluationGateStatus }) {
  return <span className={`evaluation-status evaluation-status-${status.toLowerCase()}`}>{status}</span>;
}

function SectionTitle({
  id,
  title,
  hint,
}: {
  id: string;
  title: string;
  hint: string;
}) {
  return (
    <div className="evaluation-section-heading">
      <h3 id={id}>{title}</h3>
      <p>{hint}</p>
    </div>
  );
}

function GalleryAsset({
  caseId,
  label,
  unavailable,
  url,
}: {
  caseId: string;
  label: string;
  unavailable: string;
  url: string | null;
}) {
  return (
    <div className="evaluation-gallery-asset">
      <span>{label}</span>
      {url ? (
        <img
          src={url}
          alt={`${caseId} — ${label}`}
          loading="lazy"
          decoding="async"
        />
      ) : (
        <div className="evaluation-gallery-asset-missing" role="img" aria-label={`${label}: ${unavailable}`}>
          <span aria-hidden="true">∅</span>
          <small>{unavailable}</small>
        </div>
      )}
    </div>
  );
}

function GalleryCase({ item, copy }: { item: EvaluationGalleryItem; copy: Copy }) {
  const evaluationCopy = copy.evaluation;
  const assets = [
    [evaluationCopy.referenceAsset, item.assets.reference_image_url],
    [evaluationCopy.inspectionAsset, item.assets.inspection_image_url],
    [evaluationCopy.authoritativeMaskAsset, item.assets.authoritative_mask_url],
    [evaluationCopy.predictedMaskAsset, item.assets.predicted_mask_url],
    [evaluationCopy.overlayAsset, item.assets.overlay_url],
  ] as const;
  const hashes = [
    [evaluationCopy.sourceReferenceHash, item.source_hashes.reference_sha256],
    [evaluationCopy.sourceInspectionHash, item.source_hashes.inspection_sha256],
    [evaluationCopy.sourceAuthoritativeMaskHash, item.source_hashes.authoritative_mask_sha256],
    [evaluationCopy.sourcePredictedMaskHash, item.source_hashes.predicted_mask_sha256],
  ] as const;

  return (
    <figure>
      <figcaption>
        <div className="evaluation-gallery-heading">
          <strong>{item.case_id}</strong>
          <span>{formatIdentifierLabel(item.category)}</span>
        </div>
      </figcaption>
      <div
        className="evaluation-gallery-assets"
        role="group"
        aria-label={`${item.case_id}: ${evaluationCopy.galleryTitle}`}
      >
        {assets.map(([label, url]) => (
          <GalleryAsset
            caseId={item.case_id}
            key={label}
            label={label}
            unavailable={evaluationCopy.assetUnavailable}
            url={url}
          />
        ))}
      </div>
      <div className="evaluation-gallery-evidence">
        <dl className="evaluation-gallery-metadata">
          <div><dt>{evaluationCopy.category}</dt><dd>{formatIdentifierLabel(item.category)}</dd></div>
          <div><dt>{evaluationCopy.part}</dt><dd>{item.part_id}</dd></div>
          <div><dt>{evaluationCopy.cadRevision}</dt><dd>{item.cad_revision}</dd></div>
          <div>
            <dt>{evaluationCopy.expectedFeature}</dt>
            <dd>{item.expected_feature_id ?? evaluationCopy.notRecorded}</dd>
          </div>
          <div>
            <dt>{evaluationCopy.predictedFeature}</dt>
            <dd>{item.predicted_feature_id ?? evaluationCopy.notRecorded}</dd>
          </div>
          <div><dt>{evaluationCopy.score}</dt><dd>{item.score === null ? "—" : String(item.score)}</dd></div>
          <div><dt>{evaluationCopy.galleryThreshold}</dt><dd>{item.threshold.toFixed(4)}</dd></div>
          <div>
            <dt>{evaluationCopy.failureReason}</dt>
            <dd>{item.failure_reason ?? evaluationCopy.notRecorded}</dd>
          </div>
        </dl>
        <div className="evaluation-source-hashes">
          <h4>{evaluationCopy.sourceHashes}</h4>
          <dl>
            {hashes.map(([label, digest]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{digest ? <code>{digest}</code> : evaluationCopy.notRecorded}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </figure>
  );
}

function ProfileSelector({
  copy,
  profile,
  publishedCaseCount,
  loading,
  onChange,
}: {
  copy: Copy;
  profile: EvaluationProfile;
  publishedCaseCount: number | null;
  loading: boolean;
  onChange: (profile: EvaluationProfile) => Promise<void>;
}) {
  const evaluationCopy = copy.evaluation;
  return (
    <section className="evaluation-profile-card evaluation-profile-selector" aria-labelledby="evaluation-profile-title">
      <span id="evaluation-profile-title">{evaluationCopy.profileContract}</span>
      <div
        className="profile-contract-grid"
        role="group"
        aria-label={evaluationCopy.selectProfile}
      >
        {(["mini", "full"] as const).map((optionProfile) => (
          <button
            className={profile === optionProfile ? "is-active" : ""}
            type="button"
            aria-pressed={profile === optionProfile}
            disabled={loading}
            key={optionProfile}
            onClick={() => void onChange(optionProfile)}
          >
            <span>
              {optionProfile === "mini" ? evaluationCopy.miniProfile : evaluationCopy.fullProfile}
              {profile === optionProfile ? ` · ${evaluationCopy.activeProfile}` : ""}
            </span>
            <strong>{PROFILE_CASE_COUNTS[optionProfile]}</strong>
            <small>{evaluationCopy.cases}</small>
          </button>
        ))}
      </div>
      {publishedCaseCount !== null ? (
        <p>
          {publishedCaseCount.toLocaleString()} / {PROFILE_CASE_COUNTS[profile].toLocaleString()}
          {` ${evaluationCopy.profileCases}`}
        </p>
      ) : null}
    </section>
  );
}

function EvaluationState({
  state,
  error,
  copy,
  onRefresh,
}: Pick<EvaluationWorkspaceProps, "state" | "error" | "copy" | "onRefresh">) {
  if (state === "loading") {
    return (
      <div className="evaluation-state" role="status" aria-live="polite">
        <span className="evaluation-spinner" aria-hidden="true" />
        <div>
          <h3>{copy.evaluation.loadingTitle}</h3>
          <p>{copy.evaluation.loadingText}</p>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="evaluation-state evaluation-state-error" role="alert">
        <span className="evaluation-state-mark" aria-hidden="true">!</span>
        <div>
          <h3>{copy.evaluation.errorTitle}</h3>
          <p>{copy.evaluation.errorText}</p>
          {error ? <code>{error}</code> : null}
          <button className="button button-secondary" type="button" onClick={() => void onRefresh()}>
            {copy.evaluation.retry}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="evaluation-state" role="status">
      <span className="evaluation-state-mark" aria-hidden="true">◇</span>
      <div>
        <h3>{copy.evaluation.emptyTitle}</h3>
        <p>{copy.evaluation.emptyText}</p>
        <button className="button button-secondary" type="button" onClick={() => void onRefresh()}>
          {copy.evaluation.refresh}
        </button>
      </div>
    </div>
  );
}

export function EvaluationWorkspace({
  copy,
  locale,
  snapshot,
  profile,
  state,
  error,
  onRefresh,
  onProfileChange,
}: EvaluationWorkspaceProps) {
  const evaluationCopy = copy.evaluation;

  return (
    <section className="evaluation-workspace" aria-labelledby="evaluation-title">
      <header className="evaluation-hero">
        <div>
          <p className="section-kicker">{evaluationCopy.kicker}</p>
          <h2 id="evaluation-title">{evaluationCopy.title}</h2>
          <p className="evaluation-summary">{evaluationCopy.summary}</p>
        </div>
        <button
          className="button button-quiet evaluation-refresh"
          type="button"
          disabled={state === "loading"}
          onClick={() => void onRefresh()}
        >
          <span aria-hidden="true">↻</span>
          {evaluationCopy.refresh}
        </button>
      </header>

      <div className="evaluation-boundary" role="note">
        <strong>{evaluationCopy.boundaryBadge}</strong>
        <p>{evaluationCopy.boundaryText}</p>
      </div>

      <ProfileSelector
        copy={copy}
        profile={profile}
        publishedCaseCount={
          state === "ready" && snapshot?.profile === profile ? snapshot.case_count : null
        }
        loading={state === "loading"}
        onChange={onProfileChange}
      />

      {state !== "ready" || !snapshot ? (
        <EvaluationState state={state} error={error} copy={copy} onRefresh={onRefresh} />
      ) : (
        <div className="evaluation-results">
          <section className="evaluation-overview" aria-label={evaluationCopy.latestSnapshot}>
            <article className={`evaluation-verdict verdict-${snapshot.verdict.toLowerCase()}`}>
              <span>{evaluationCopy.verdict}</span>
              <strong>{snapshot.verdict}</strong>
              <p>
                {snapshot.verdict === "PASS"
                  ? evaluationCopy.passMeaning
                  : evaluationCopy.holdMeaning}
              </p>
            </article>

            <article className="evaluation-run-card">
              <span>{evaluationCopy.latestSnapshot}</span>
              <strong>{snapshot.evaluation_run_id}</strong>
              <dl>
                <div>
                  <dt>{evaluationCopy.inferenceCases}</dt>
                  <dd>{snapshot.inference_case_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>{evaluationCopy.trustCases}</dt>
                  <dd>{snapshot.trust_boundary_case_count.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>{evaluationCopy.generatedAt}</dt>
                  <dd>{formatDate(snapshot.generated_at, locale)}</dd>
                </div>
              </dl>
            </article>
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-gates-title">
            <SectionTitle id="evaluation-gates-title" title={evaluationCopy.gatesTitle} hint={evaluationCopy.gatesHint} />
            {snapshot.gates.length > 0 ? <div
              className="evaluation-table-scroll"
              role="region"
              aria-label={evaluationCopy.gatesTable}
              tabIndex={0}
            >
              <table>
                <caption className="sr-only">{evaluationCopy.gatesTable}</caption>
                <thead>
                  <tr>
                    <th scope="col">{evaluationCopy.gate}</th>
                    <th scope="col">{evaluationCopy.observed}</th>
                    <th scope="col">{evaluationCopy.required}</th>
                    <th scope="col">{evaluationCopy.evidenceCount}</th>
                    <th scope="col">{evaluationCopy.status}</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.gates.map((gate) => (
                    <tr key={gate.gate_id}>
                      <th scope="row">
                        <span>{gateLabel(copy, gate.gate_id, gate.label)}</span>
                        <code>{gate.gate_id}</code>
                        {gate.reason ? <small>{gate.reason}</small> : null}
                      </th>
                      <td>{gate.observed}</td>
                      <td>{gate.threshold}</td>
                      <td>{formatEvidenceCount(gate.numerator, gate.denominator)}</td>
                      <td><StatusBadge status={gate.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div> : <p className="evaluation-section-empty">{evaluationCopy.noGates}</p>}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-metrics-title">
            <SectionTitle id="evaluation-metrics-title" title={evaluationCopy.metricsTitle} hint={evaluationCopy.metricsHint} />
            {snapshot.metrics.length > 0 ? (
              <div className="evaluation-metric-grid">
                {snapshot.metrics.map((metric) => (
                  <article key={metric.metric_id}>
                    <span>{metricLabel(copy, metric.metric_id, metric.label)}</span>
                    <strong>{formatMetricValue(metric)}</strong>
                    <small>
                      {metric.value === null
                        ? metric.undefined_reason ?? evaluationCopy.undefinedMetric
                        : formatEvidenceCount(metric.numerator, metric.denominator)}
                    </small>
                  </article>
                ))}
              </div>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noMetrics}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-confusion-title">
            <SectionTitle
              id="evaluation-confusion-title"
              title={evaluationCopy.confusionTitle}
              hint={evaluationCopy.confusionHint}
            />
            {snapshot.confusion_matrix ? (
              <div
                className="evaluation-table-scroll"
                role="region"
                aria-label={evaluationCopy.confusionTable}
                tabIndex={0}
              >
                <table className="evaluation-confusion-table">
                  <caption className="sr-only">{evaluationCopy.confusionTable}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{evaluationCopy.actualOutcome}</th>
                      <th scope="col">{evaluationCopy.predictedAnomaly}</th>
                      <th scope="col">{evaluationCopy.predictedNormal}</th>
                      <th scope="col">{evaluationCopy.totalEvaluated}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th scope="row">{evaluationCopy.actualAnomaly}</th>
                      <td aria-label={`${evaluationCopy.truePositive}: ${snapshot.confusion_matrix.true_positive}`}>
                        <span>TP</span>
                        <strong>{snapshot.confusion_matrix.true_positive.toLocaleString()}</strong>
                      </td>
                      <td aria-label={`${evaluationCopy.falseNegative}: ${snapshot.confusion_matrix.false_negative}`}>
                        <span>FN</span>
                        <strong>{snapshot.confusion_matrix.false_negative.toLocaleString()}</strong>
                      </td>
                      <td>{(
                        snapshot.confusion_matrix.true_positive
                        + snapshot.confusion_matrix.false_negative
                      ).toLocaleString()}</td>
                    </tr>
                    <tr>
                      <th scope="row">{evaluationCopy.actualNormal}</th>
                      <td aria-label={`${evaluationCopy.falsePositive}: ${snapshot.confusion_matrix.false_positive}`}>
                        <span>FP</span>
                        <strong>{snapshot.confusion_matrix.false_positive.toLocaleString()}</strong>
                      </td>
                      <td aria-label={`${evaluationCopy.trueNegative}: ${snapshot.confusion_matrix.true_negative}`}>
                        <span>TN</span>
                        <strong>{snapshot.confusion_matrix.true_negative.toLocaleString()}</strong>
                      </td>
                      <td>{(
                        snapshot.confusion_matrix.false_positive
                        + snapshot.confusion_matrix.true_negative
                      ).toLocaleString()}</td>
                    </tr>
                  </tbody>
                  <tfoot>
                    <tr>
                      <th scope="row">{evaluationCopy.totalEvaluated}</th>
                      <td>{(
                        snapshot.confusion_matrix.true_positive
                        + snapshot.confusion_matrix.false_positive
                      ).toLocaleString()}</td>
                      <td>{(
                        snapshot.confusion_matrix.false_negative
                        + snapshot.confusion_matrix.true_negative
                      ).toLocaleString()}</td>
                      <td>{snapshot.confusion_matrix.sample_count.toLocaleString()}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noConfusion}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-distribution-title">
            <SectionTitle
              id="evaluation-distribution-title"
              title={evaluationCopy.distributionTitle}
              hint={evaluationCopy.distributionHint}
            />
            {snapshot.positive_case_distribution.length > 0 ? (
              <>
                <p className="gallery-count" role="status">
                  {evaluationCopy.showingDistribution}
                  {` ${snapshot.positive_case_distribution.length.toLocaleString()} ${evaluationCopy.positiveCases}`}
                </p>
                <div
                  className="evaluation-table-scroll evaluation-distribution-scroll"
                  role="region"
                  aria-label={evaluationCopy.distributionTable}
                  tabIndex={0}
                >
                  <table>
                    <caption className="sr-only">{evaluationCopy.distributionTable}</caption>
                    <thead>
                      <tr>
                        <th scope="col">{evaluationCopy.caseId}</th>
                        <th scope="col">{evaluationCopy.defectType}</th>
                        <th scope="col">{evaluationCopy.severity}</th>
                        <th scope="col">{evaluationCopy.dice}</th>
                        <th scope="col">{evaluationCopy.iou}</th>
                        <th scope="col">{evaluationCopy.truthPixels}</th>
                        <th scope="col">{evaluationCopy.predictedPixels}</th>
                        <th scope="col">{evaluationCopy.intersectionPixels}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshot.positive_case_distribution.map((item) => (
                        <tr key={item.case_id}>
                          <th scope="row"><code>{item.case_id}</code></th>
                          <td>{item.defect_type ? formatIdentifierLabel(item.defect_type) : "—"}</td>
                          <td>{item.severity ?? "—"}</td>
                          <td>{item.dice.toFixed(4)}</td>
                          <td>{item.iou.toFixed(4)}</td>
                          <td>{item.truth_positive_pixels.toLocaleString()}</td>
                          <td>{item.predicted_positive_pixels.toLocaleString()}</td>
                          <td>{item.intersection_pixels.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noDistribution}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-slices-title">
            <SectionTitle id="evaluation-slices-title" title={evaluationCopy.slicesTitle} hint={evaluationCopy.slicesHint} />
            {snapshot.slices.length > 0 ? (
              <div
                className="evaluation-table-scroll"
                role="region"
                aria-label={evaluationCopy.slicesTable}
                tabIndex={0}
              >
                <table>
                  <caption className="sr-only">{evaluationCopy.slicesTable}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{evaluationCopy.slice}</th>
                      <th scope="col">{evaluationCopy.sampleCount}</th>
                      <th scope="col">{evaluationCopy.metric}</th>
                      <th scope="col">{evaluationCopy.value}</th>
                      <th scope="col">{evaluationCopy.evidenceCount}</th>
                    </tr>
                  </thead>
                  {snapshot.slices.map((slice) => (
                    <tbody key={slice.slice_id}>
                      {slice.metrics.map((metric, index) => (
                        <tr key={`${slice.slice_id}-${metric.metric_id}`}>
                          {index === 0 ? (
                            <th scope="rowgroup" rowSpan={slice.metrics.length}>
                              <span>{sliceLabel(copy, slice)}</span>
                              <code>{slice.slice_id}</code>
                            </th>
                          ) : null}
                          {index === 0 ? <td rowSpan={slice.metrics.length}>{slice.sample_count}</td> : null}
                          <th scope="row">{metricLabel(copy, metric.metric_id, metric.label)}</th>
                          <td>{formatMetricValue(metric)}</td>
                          <td>{formatEvidenceCount(metric.numerator, metric.denominator)}</td>
                        </tr>
                      ))}
                    </tbody>
                  ))}
                </table>
              </div>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noSlices}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-trust-title">
            <SectionTitle id="evaluation-trust-title" title={evaluationCopy.trustTitle} hint={evaluationCopy.trustHint} />
            {snapshot.trust_boundary.length > 0 ? (
              <div
                className="evaluation-table-scroll"
                role="region"
                aria-label={evaluationCopy.trustTable}
                tabIndex={0}
              >
                <table>
                  <caption className="sr-only">{evaluationCopy.trustTable}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{evaluationCopy.caseId}</th>
                      <th scope="col">{evaluationCopy.expectedCode}</th>
                      <th scope="col">{evaluationCopy.observedCode}</th>
                      <th scope="col">{evaluationCopy.publishedArtifacts}</th>
                      <th scope="col">{evaluationCopy.status}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.trust_boundary.map((trustCase) => (
                      <tr key={trustCase.case_id}>
                        <th scope="row">
                          <span>{formatIdentifierLabel(trustCase.label)}</span>
                          <code>{trustCase.case_id}</code>
                        </th>
                        <td><code>{trustCase.expected_code}</code></td>
                        <td><code>{trustCase.observed_code}</code></td>
                        <td>{trustCase.published_artifact_count}</td>
                        <td><StatusBadge status={trustCase.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noTrustCases}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-gallery-title">
            <SectionTitle id="evaluation-gallery-title" title={evaluationCopy.galleryTitle} hint={evaluationCopy.galleryHint} />
            {snapshot.gallery.length > 0 ? (
              <>
                <p className="gallery-count" role="status">
                  {evaluationCopy.showingGallery} {Math.min(snapshot.gallery.length, GALLERY_LIMIT)}
                  {` ${evaluationCopy.ofGallery} ${snapshot.gallery_total} ${evaluationCopy.galleryItems}`}
                </p>
                <div className="evaluation-gallery">
                  {snapshot.gallery.slice(0, GALLERY_LIMIT).map((item) => (
                    <GalleryCase key={item.gallery_item_id} item={item} copy={copy} />
                  ))}
                </div>
              </>
            ) : (
              <p className="evaluation-section-empty">{evaluationCopy.noGallery}</p>
            )}
          </section>

          <section className="evaluation-section" aria-labelledby="evaluation-reproduction-title">
            <SectionTitle
              id="evaluation-reproduction-title"
              title={evaluationCopy.reproductionTitle}
              hint={evaluationCopy.reproductionHint}
            />
            <ol
              className="evaluation-reproduction-commands"
              aria-label={evaluationCopy.reproductionCommands}
            >
              {REPRODUCTION_COMMANDS.map((command) => (
                <li key={command}><code>{command}</code></li>
              ))}
            </ol>
          </section>

          <div className="evaluation-bottom-grid">
            <section className="evaluation-section" aria-labelledby="evaluation-lineage-title">
              <h3 id="evaluation-lineage-title">{evaluationCopy.lineageTitle}</h3>
              <dl className="evaluation-lineage">
                <div><dt>{evaluationCopy.protocol}</dt><dd>{snapshot.protocol_id}@{snapshot.protocol_version}</dd></div>
                <div><dt>{evaluationCopy.dataset}</dt><dd>{snapshot.dataset_id}@{snapshot.dataset_version}</dd></div>
                <div><dt>{evaluationCopy.baseline}</dt><dd>{snapshot.baseline.pipeline_id}@{snapshot.baseline.pipeline_version}</dd></div>
                <div><dt>{evaluationCopy.imageThreshold}</dt><dd>{snapshot.baseline.locked_image_threshold.toFixed(4)}</dd></div>
                <div><dt>{evaluationCopy.thresholdSource}</dt><dd>{snapshot.baseline.threshold_source_split}</dd></div>
                <div><dt>{evaluationCopy.thresholdLock}</dt><dd>{snapshot.baseline.threshold_lock_status}</dd></div>
                <div><dt>{evaluationCopy.datasetHash}</dt><dd><code>{snapshot.dataset_manifest_sha256}</code></dd></div>
                <div><dt>{evaluationCopy.configurationHash}</dt><dd><code>{snapshot.baseline.configuration_sha256}</code></dd></div>
                <div><dt>{evaluationCopy.resultHash}</dt><dd><code>{snapshot.result_sha256}</code></dd></div>
                <div><dt>{evaluationCopy.commit}</dt><dd><code>{snapshot.code_commit_sha}</code></dd></div>
                <div>
                  <dt>{evaluationCopy.worktree}</dt>
                  <dd className={snapshot.dirty_worktree ? "danger-text" : "success-text"}>
                    {snapshot.dirty_worktree ? evaluationCopy.dirty : evaluationCopy.clean}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="evaluation-section" aria-labelledby="evaluation-limitations-title">
              <h3 id="evaluation-limitations-title">{evaluationCopy.limitationsTitle}</h3>
              <ul className="evaluation-limitations">
                {snapshot.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
              </ul>
              <h4>{evaluationCopy.exclusionsTitle}</h4>
              <ul className="evaluation-limitations">
                {snapshot.exclusions.map((exclusion) => <li key={exclusion}>{exclusion}</li>)}
              </ul>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}
