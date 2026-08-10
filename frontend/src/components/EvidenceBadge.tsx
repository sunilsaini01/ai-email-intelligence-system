import type { EvidenceBadge as EvidenceBadgeType } from "../types/dashboard";

// FR-53/57's non-negotiable requirement: never let a chart imply a
// number is validated production accuracy when it isn't. Every dashboard
// number derived from a classifier renders one of these next to it --
// see docs/architecture_dashboard.md "Model evidence policy".
const COLORS: Record<EvidenceBadgeType["status"], string> = {
  REAL_VALIDATED: "#1b7f3a",
  SYNTHETIC: "#a15c00",
  OFF_DOMAIN: "#1d5c8a",
  UNVALIDATED: "#7a1fa0",
  PROVISIONAL: "#8a1f1f",
};

const LABELS: Record<EvidenceBadgeType["status"], string> = {
  REAL_VALIDATED: "Real, validated",
  SYNTHETIC: "Synthetic labels",
  OFF_DOMAIN: "Off-domain",
  UNVALIDATED: "Unvalidated",
  PROVISIONAL: "Provisional",
};

export function EvidenceBadge({ evidence }: { evidence: EvidenceBadgeType }) {
  return (
    <span className="evidence-badge" style={{ backgroundColor: COLORS[evidence.status] }} title={evidence.note}>
      {LABELS[evidence.status]}
    </span>
  );
}
