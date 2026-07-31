import type { ChangeEvent } from "react";
import type { Copy } from "../copy";
import type { InspectionCase } from "../types";
import { PartPreview } from "./PartPreview";
import { StatusPill } from "./StatusPill";

interface InspectionWorkspaceProps {
  inspectionCase: InspectionCase;
  copy: Copy;
  busy: boolean;
  showOverlay: boolean;
  onOverlayChange: (value: boolean) => void;
  onAnalyze: () => Promise<void>;
  onUploadReference: (file: File) => Promise<void>;
  onUploadInspection: (file: File) => Promise<void>;
}

function ImageUpload({
  label,
  accept,
  disabled,
  onFile,
}: {
  label: string;
  accept: string;
  disabled: boolean;
  onFile: (file: File) => Promise<void>;
}) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void onFile(file);
    event.target.value = "";
  }

  return (
    <label className={`button button-quiet upload-button ${disabled ? "is-disabled" : ""}`}>
      <span aria-hidden="true">↑</span>
      {label}
      <input disabled={disabled} type="file" accept={accept} onChange={handleChange} />
    </label>
  );
}

function formatScore(value: number | undefined): string {
  return typeof value === "number" ? value.toFixed(3) : "—";
}

export function InspectionWorkspace({
  inspectionCase,
  copy,
  busy,
  showOverlay,
  onOverlayChange,
  onAnalyze,
  onUploadReference,
  onUploadInspection,
}: InspectionWorkspaceProps) {
  const analysis = inspectionCase.analysis;
  const inspectionImage = inspectionCase.inspection_images[0];
  const mappedFeatures = analysis?.feature_mappings.filter(
    (feature) => feature.feature_id !== "unmapped" && feature.anomaly_score > 0,
  ) ?? [];
  const topFeature = [...mappedFeatures].sort(
    (left, right) => right.anomaly_score - left.anomaly_score,
  )[0];

  return (
    <section className="workspace-card" aria-labelledby="workspace-title">
      <div className="workspace-header">
        <div className="case-identity">
          <p className="section-kicker">{copy.workspace}</p>
          <div className="identity-line">
            <h2 id="workspace-title">{inspectionCase.part_id}</h2>
            <span className="revision-chip">{inspectionCase.revision}</span>
            <StatusPill status={inspectionCase.status} />
          </div>
          <p className="case-id">
            CASE · {(inspectionCase.id || inspectionCase.case_id || "").toUpperCase()} · STATE REV {inspectionCase.case_revision ?? 1}
          </p>
        </div>
        <div className="workspace-actions">
          <ImageUpload
            label={copy.uploadReference}
            accept="image/png,image/jpeg"
            disabled={busy}
            onFile={onUploadReference}
          />
          <ImageUpload
            label={copy.uploadInspection}
            accept="image/png,image/jpeg"
            disabled={busy}
            onFile={onUploadInspection}
          />
          <button
            className="button button-primary"
            type="button"
            disabled={busy || !inspectionCase.reference_image || inspectionCase.inspection_images.length === 0}
            onClick={() => void onAnalyze()}
          >
            <span aria-hidden="true">◎</span>
            {busy ? copy.processing : analysis ? copy.rerun : copy.run}
          </button>
        </div>
      </div>

      <div className="comparison-toolbar">
        <div className="view-legend" aria-label="Image comparison legend">
          <span><span className="legend-dot reference-dot" />{copy.reference}</span>
          <span><span className="legend-dot inspection-dot" />{copy.inspection}</span>
        </div>
        <label className="overlay-toggle">
          <span>{copy.overlay}</span>
          <input
            type="checkbox"
            checked={showOverlay}
            disabled={!analysis}
            onChange={(event) => onOverlayChange(event.target.checked)}
          />
          <span className="toggle-track" aria-hidden="true"><span /></span>
        </label>
      </div>

      <div className="image-comparison">
        <figure>
          <figcaption>
            <span>{copy.reference}</span>
            <span className="image-filename">{inspectionCase.reference_image?.filename ?? "reference.png"}</span>
          </figcaption>
          <PartPreview
            variant="reference"
            showOverlay={false}
            imageUrl={inspectionCase.reference_image?.url}
            alt={`${copy.reference}: ${inspectionCase.part_id} ${inspectionCase.revision}`}
          />
        </figure>
        <figure>
          <figcaption>
            <span>{copy.inspection}</span>
            <span className="image-filename">{inspectionImage?.filename ?? "inspection.png"}</span>
          </figcaption>
          <PartPreview
            variant="inspection"
            showOverlay={Boolean(analysis && showOverlay)}
            imageUrl={inspectionImage?.url}
            maskUrl={analysis?.mask_url ?? analysis?.mask?.url}
            alt={`${copy.inspection}: ${inspectionCase.part_id} ${inspectionCase.revision}`}
          />
        </figure>
      </div>

      <div className="metrics-strip" aria-label="Inspection metrics">
        <div className="metric-primary">
          <span>{copy.anomalyScore}</span>
          <strong>{formatScore(analysis?.anomaly_score)}</strong>
          <div className="score-bar" aria-hidden="true">
            <span style={{ width: `${Math.min(100, (analysis?.anomaly_score ?? 0) * 100)}%` }} />
            <i style={{ left: `${Math.min(100, (analysis?.threshold ?? 0.18) * 100)}%` }} />
          </div>
        </div>
        <div className="metric-cell">
          <span>{copy.threshold}</span>
          <strong>{formatScore(analysis?.threshold)}</strong>
        </div>
        <div className="metric-cell">
          <span>{copy.modelVerdict}</span>
          <strong className={analysis?.verdict === "anomaly" ? "danger-text" : ""}>
            {analysis?.verdict?.toUpperCase() ?? "—"}
          </strong>
        </div>
        <div className="metric-cell feature-cell">
          <span>{copy.affectedFeature}</span>
          <strong>{topFeature?.label ?? topFeature?.feature_id ?? (analysis ? copy.unmapped : "—")}</strong>
          <small>{topFeature ? `${formatScore(topFeature.anomaly_score)} ${copy.normalizedDifference}` : analysis ? copy.unmapped : copy.noAnalysis}</small>
        </div>
        <div className="metric-cell pipeline-cell">
          <span>{copy.pipeline}</span>
          <strong>{analysis?.pipeline_version ?? "baseline.diff/1"}</strong>
          <small>{analysis?.model_version ?? "deterministic"}</small>
        </div>
      </div>
    </section>
  );
}
