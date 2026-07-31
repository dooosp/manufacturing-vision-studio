import type { Copy } from "../copy";
import type { InspectionCase } from "../types";

interface EvidencePanelProps {
  inspectionCase: InspectionCase;
  copy: Copy;
}

function shortHash(value?: string): string {
  if (!value) return "—";
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

export function EvidencePanel({ inspectionCase, copy }: EvidencePanelProps) {
  const analysis = inspectionCase.analysis;
  const evidence = [
    { label: copy.caseIdentity, ready: Boolean(inspectionCase.part_id && inspectionCase.revision), value: `${inspectionCase.part_id} · ${inspectionCase.revision}` },
    { label: copy.caseRevision, ready: Boolean(inspectionCase.case_revision), value: `R${inspectionCase.case_revision ?? 1}` },
    { label: copy.referenceHash, ready: Boolean(inspectionCase.reference_image?.sha256), value: shortHash(inspectionCase.reference_image?.sha256) },
    { label: copy.inputHash, ready: Boolean(inspectionCase.inspection_images[0]?.sha256), value: shortHash(inspectionCase.inspection_images[0]?.sha256) },
    { label: copy.configHash, ready: Boolean(analysis?.configuration_hash), value: shortHash(analysis?.configuration_hash) },
    { label: copy.maskHash, ready: Boolean(analysis?.mask?.sha256), value: shortHash(analysis?.mask?.sha256) },
    { label: copy.reviewRecord, ready: Boolean(inspectionCase.disposition), value: inspectionCase.disposition?.decision ?? "—" },
  ];

  const completed = evidence.filter((item) => item.ready).length;

  return (
    <section className="side-panel evidence-panel" aria-labelledby="evidence-title">
      <div className="panel-title-row">
        <div>
          <p className="section-kicker">Lineage</p>
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
