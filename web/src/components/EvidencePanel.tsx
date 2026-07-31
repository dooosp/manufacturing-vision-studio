import type { Copy } from "../copy";
import type { InspectionCase } from "../types";

interface EvidencePanelProps {
  inspectionCase: InspectionCase;
  copy: Copy;
}

function displayHash(value?: string): string {
  return value || "—";
}

export function EvidencePanel({ inspectionCase, copy }: EvidencePanelProps) {
  const analysis = inspectionCase.analysis;
  const analyzedInspection = analysis
    ? inspectionCase.inspection_images.find(
        (image) => image.id === analysis.inspection_image_id,
      )
    : inspectionCase.inspection_images[0];
  const evidence = [
    { label: copy.caseIdentity, ready: Boolean(inspectionCase.part_id && inspectionCase.revision), value: `${inspectionCase.part_id} · ${inspectionCase.revision}` },
    { label: copy.caseRevision, ready: Boolean(inspectionCase.case_revision), value: `R${inspectionCase.case_revision ?? 1}` },
    { label: copy.referenceHash, ready: Boolean(inspectionCase.reference_image?.sha256), value: displayHash(inspectionCase.reference_image?.sha256) },
    { label: copy.inputHash, ready: Boolean(analyzedInspection?.sha256), value: displayHash(analyzedInspection?.sha256) },
    { label: copy.configHash, ready: Boolean(analysis?.configuration_hash), value: displayHash(analysis?.configuration_hash) },
    { label: copy.maskHash, ready: Boolean(analysis?.mask?.sha256), value: displayHash(analysis?.mask?.sha256) },
    { label: copy.reviewRecord, ready: Boolean(inspectionCase.disposition), value: inspectionCase.disposition?.decision ?? "—" },
  ];

  const completed = evidence.filter((item) => item.ready).length;

  return (
    <section className="side-panel evidence-panel" aria-labelledby="evidence-title">
      <div className="panel-title-row">
        <div>
          <p className="section-kicker">{copy.lineage}</p>
          <h2 id="evidence-title">{copy.evidence}</h2>
        </div>
        <span className="evidence-count">{completed}/{evidence.length}</span>
      </div>
      <p className="panel-description">{copy.evidenceHint}</p>
      <div className="evidence-progress" aria-hidden="true">
        <span style={{ width: `${(completed / evidence.length) * 100}%` }} />
      </div>
      <dl className="evidence-list">
        {evidence.map((item) => (
          <div key={item.label} className={item.ready ? "is-ready" : "is-missing"}>
            <dt>
              <span className="evidence-icon" aria-hidden="true">{item.ready ? "✓" : "·"}</span>
              {item.label}
            </dt>
            <dd>
              <span className="evidence-value">{item.value}</span>
              <span className="sr-only">{item.ready ? copy.ready : copy.missing}</span>
            </dd>
          </div>
        ))}
      </dl>
      <div className="boundary-note">
        <span aria-hidden="true">△</span>
        <div>
          <strong>{copy.limitations}</strong>
          <p>{copy.limitationText}</p>
        </div>
      </div>
    </section>
  );
}
