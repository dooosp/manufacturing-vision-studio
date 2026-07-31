import { useEffect, useState } from "react";
import type { Copy } from "../copy";
import type { Decision, HumanDisposition } from "../types";

interface DispositionPanelProps {
  current?: HumanDisposition | null;
  copy: Copy;
  disabled: boolean;
  exporting: boolean;
  onSubmit: (decision: Decision, reviewer: string, note: string) => Promise<void>;
  onExport: () => Promise<void>;
}

const decisions: Decision[] = ["accept", "reject", "needs_review", "model_error"];

export function DispositionPanel({
  current,
  copy,
  disabled,
  exporting,
  onSubmit,
  onExport,
}: DispositionPanelProps) {
  const [decision, setDecision] = useState<Decision>(current?.decision ?? "needs_review");
  const [reviewer, setReviewer] = useState(current?.reviewer ?? "");
  const [note, setNote] = useState(current?.note ?? "");

  useEffect(() => {
    if (!current) return;
    setDecision(current.decision);
    setReviewer(current.reviewer);
    setNote(current.note);
  }, [current]);

  const labels: Record<Decision, string> = {
    accept: copy.accept,
    reject: copy.reject,
    needs_review: copy.needsReview,
    model_error: copy.modelError,
  };

  return (
    <section className="side-panel disposition-panel" aria-labelledby="disposition-title">
      <div className="panel-title-row">
        <div>
          <p className="section-kicker">{copy.humanLoop}</p>
          <h2 id="disposition-title">{copy.disposition}</h2>
        </div>
        <span className="review-icon" aria-hidden="true">⌁</span>
      </div>
      <p className="panel-description">{copy.dispositionHint}</p>

      <div className="decision-grid" role="radiogroup" aria-label={copy.disposition}>
        {decisions.map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={decision === value}
            className={`decision-button decision-${value.toLowerCase()} ${decision === value ? "is-selected" : ""}`}
            disabled={disabled}
            onClick={() => setDecision(value)}
          >
            <span className="decision-symbol" aria-hidden="true">
              {value === "accept" ? "✓" : value === "reject" ? "×" : value === "model_error" ? "!" : "?"}
            </span>
            {labels[value]}
          </button>
        ))}
      </div>

      <label className="field-label">
        <span>{copy.reviewer}</span>
        <input
          value={reviewer}
          disabled={disabled}
          placeholder={copy.defaultReviewer}
          onChange={(event) => setReviewer(event.target.value)}
          autoComplete="name"
        />
      </label>
      <label className="field-label">
        <span>{copy.note}</span>
        <textarea
          value={note}
          disabled={disabled}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          placeholder={copy.notePlaceholder}
        />
      </label>

      <button
        className="button button-primary button-full"
        type="button"
        disabled={disabled || !reviewer.trim() || !note.trim()}
        onClick={() => void onSubmit(decision, reviewer.trim(), note.trim())}
      >
        {copy.record}
      </button>
      <button
        className="button button-export button-full"
        type="button"
        disabled={!current || exporting}
        onClick={() => void onExport()}
      >
        <span aria-hidden="true">⇩</span>
        {exporting ? copy.exporting : copy.export}
      </button>
    </section>
  );
}
