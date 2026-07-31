import type { Copy } from "../copy";
import type { CaseStatus } from "../types";

export function StatusPill({ status, copy }: { status: CaseStatus; copy: Copy }) {
  const labels: Record<CaseStatus, string> = {
    draft: copy.statusDraft,
    ready: copy.statusReady,
    analyzed: copy.statusAnalyzed,
    disposed: copy.statusDisposed,
    exported: copy.statusExported,
    failed: copy.statusFailed,
  };
  return <span className={`status-pill status-${status.toLowerCase()}`}>{labels[status]}</span>;
}
