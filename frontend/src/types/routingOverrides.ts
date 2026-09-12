// Mirrors backend/app/schemas/routing_override.py and
// backend/app/routing/overrides.py's CONDITION_FIELDS/CONDITION_OPERATORS
// constants exactly -- see api/dashboard.ts's own comment on why these
// stay hand-kept in sync rather than generated.

export const CONDITION_FIELDS = [
  "category",
  "priority",
  "sentiment",
  "is_spam",
  "intent",
  "sender_domain_type",
  "sender_email_domain",
  "subject_contains",
  "body_contains",
] as const;
export type ConditionField = (typeof CONDITION_FIELDS)[number];

export const CONDITION_OPERATORS = ["eq", "in", "contains"] as const;
export type ConditionOperator = (typeof CONDITION_OPERATORS)[number];

// Mirrors backend/app/routing/department_taxonomy.py's DEPARTMENTS (Category's own FR-21 taxonomy).
export const DEPARTMENTS = ["Support", "Sales", "Billing", "Legal", "HR", "IT", "Marketing", "General"] as const;

export const ROUTING_ACTIONS = ["auto_route", "human_review", "quarantine", "fallback"] as const;
export type RoutingAction = (typeof ROUTING_ACTIONS)[number];

export interface RoutingOverrideCondition {
  field: ConditionField;
  operator: ConditionOperator;
  value: string | boolean;
}

export interface RoutingOverride {
  id: string;
  name: string;
  priority_order: number;
  is_active: boolean;
  conditions: RoutingOverrideCondition[];
  override_department: string | null;
  override_action: RoutingAction | null;
  override_requires_human_review: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface RoutingOverrideListResponse {
  overrides: RoutingOverride[];
}

export interface RoutingOverrideCreateRequest {
  name: string;
  priority_order: number;
  is_active: boolean;
  conditions: RoutingOverrideCondition[];
  override_department: string | null;
  override_action: RoutingAction | null;
  override_requires_human_review: boolean | null;
}
