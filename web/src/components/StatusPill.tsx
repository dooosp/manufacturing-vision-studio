import type { CaseStatus } from "../types";

const labels: Record<CaseStatus, string> = {
  draft: "Draft",
  ready: "Ready",
  analyzed: "Analyzed",
  disposed: "Reviewed",
  exported: "Exported",
  failed: "Blocked",
};

export function StatusPill({ status }: { status: CaseStatus }) {
  return <span className={`status-pill status-${status.toLowerCase()}`}>{labels[status]}</span>;
}
