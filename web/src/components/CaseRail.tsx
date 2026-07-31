import { useState } from "react";
import type { Copy } from "../copy";
import type { InspectionCase } from "../types";
import { StatusPill } from "./StatusPill";

interface CaseRailProps {
  cases: InspectionCase[];
  selectedId: string | null;
  copy: Copy;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: (partId: string, revision: string) => Promise<void>;
  onCreateDemo: () => Promise<void>;
}

export function CaseRail({
  cases,
  selectedId,
  copy,
  busy,
  onSelect,
  onCreate,
  onCreateDemo,
}: CaseRailProps) {
  const [showForm, setShowForm] = useState(false);
  const [partId, setPartId] = useState("");
  const [revision, setRevision] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!partId.trim() || !revision.trim()) return;
    await onCreate(partId.trim(), revision.trim());
    setPartId("");
    setRevision("");
    setShowForm(false);
  }

  return (
    <aside className="case-rail" aria-label={copy.cases}>
      <div className="rail-heading">
        <div>
          <p className="section-kicker">Case registry</p>
          <h2>{copy.cases}</h2>
        </div>
        <span className="case-count" aria-label={`${cases.length} cases`}>{cases.length}</span>
      </div>

      <button
        className="button button-secondary button-full"
        type="button"
        onClick={() => setShowForm((value) => !value)}
        aria-expanded={showForm}
      >
        <span aria-hidden="true">＋</span>
        {copy.newCase}
      </button>

      {showForm ? (
        <form className="new-case-form" onSubmit={submit}>
          <label>
            <span>{copy.partId}</span>
            <input
              value={partId}
              onChange={(event) => setPartId(event.target.value)}
              placeholder="BRACKET-A17"
              autoComplete="off"
              required
            />
          </label>
          <label>
            <span>{copy.revision}</span>
            <input
              value={revision}
              onChange={(event) => setRevision(event.target.value)}
              placeholder="REV-C"
              autoComplete="off"
              required
            />
          </label>
          <button className="button button-primary button-full" disabled={busy} type="submit">
            {busy ? copy.processing : copy.create}
          </button>
        </form>
      ) : null}

      <div className="case-list">
        {cases.map((item) => {
          const id = item.id || item.case_id || "";
          const selected = id === selectedId;
          return (
            <button
              className={`case-card ${selected ? "is-selected" : ""}`}
              type="button"
              aria-current={selected ? "true" : undefined}
              key={id}
              onClick={() => onSelect(id)}
            >
              <span className="case-card-topline">
                <span className="case-part">{item.part_id}</span>
                <StatusPill status={item.status} />
              </span>
              <span className="case-meta">
                <span>{item.revision}</span>
                <span aria-hidden="true">·</span>
                <span>{id.slice(0, 10)}</span>
              </span>
            </button>
          );
        })}
      </div>

      {cases.length === 0 ? (
        <div className="empty-cases">
          <div className="empty-glyph" aria-hidden="true">◇</div>
          <p>{copy.emptyCases}</p>
        </div>
      ) : null}

      <button
        className="demo-loader"
        type="button"
        disabled={busy}
        onClick={() => void onCreateDemo()}
      >
        <span aria-hidden="true">↻</span>
        {copy.loadDemo}
      </button>
    </aside>
  );
}
