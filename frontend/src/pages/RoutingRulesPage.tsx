import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { useRoutingOverrideMutations, useRoutingOverrides } from "../hooks/useRoutingOverrides";
import { QueryState } from "../components/QueryState";
import {
  CONDITION_FIELDS,
  CONDITION_OPERATORS,
  DEPARTMENTS,
  ROUTING_ACTIONS,
  type ConditionField,
  type ConditionOperator,
  type RoutingAction,
  type RoutingOverrideCondition,
} from "../types/routingOverrides";

const REVIEW_CHOICES = [
  { label: "Don't change", value: "" },
  { label: "Force: require review", value: "true" },
  { label: "Force: skip review", value: "false" },
];

function emptyCondition(): RoutingOverrideCondition {
  return { field: "sender_email_domain", operator: "eq", value: "" };
}

function describeCondition(c: RoutingOverrideCondition): string {
  return `${c.field} ${c.operator} "${c.value}"`;
}

function NewOverrideForm() {
  const { create } = useRoutingOverrideMutations();
  const [name, setName] = useState("");
  const [priority, setPriority] = useState(100);
  const [conditions, setConditions] = useState<RoutingOverrideCondition[]>([emptyCondition()]);
  const [department, setDepartment] = useState("");
  const [action, setAction] = useState("");
  const [review, setReview] = useState("");

  const updateCondition = (index: number, patch: Partial<RoutingOverrideCondition>) => {
    setConditions((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };

  const canSubmit = name.trim().length > 0 && conditions.every((c) => String(c.value).length > 0) && (department || action || review);

  function handleSubmit() {
    create.mutate(
      {
        name,
        priority_order: priority,
        is_active: true,
        conditions,
        override_department: department || null,
        override_action: (action || null) as RoutingAction | null,
        override_requires_human_review: review === "" ? null : review === "true",
      },
      {
        onSuccess: () => {
          setName("");
          setPriority(100);
          setConditions([emptyCondition()]);
          setDepartment("");
          setAction("");
          setReview("");
        },
      },
    );
  }

  return (
    <div className="reply-draft-card">
      <div className="reply-draft-card__subject">Add a new override</div>
      <div className="override-form-row">
        <label className="filter-field">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. VIP domain to Sales" size={30} />
        </label>
        <label className="filter-field">
          Priority (lower = evaluated first)
          <input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} size={6} />
        </label>
      </div>

      <p className="reply-draft-card__label" style={{ marginTop: 12 }}>
        Conditions (all must match)
      </p>
      {conditions.map((c, i) => (
        <div className="override-form-row" key={i}>
          <select value={c.field} onChange={(e) => updateCondition(i, { field: e.target.value as ConditionField })}>
            {CONDITION_FIELDS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select value={c.operator} onChange={(e) => updateCondition(i, { operator: e.target.value as ConditionOperator })}>
            {CONDITION_OPERATORS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
          <input
            value={String(c.value)}
            onChange={(e) => updateCondition(i, { value: e.target.value })}
            placeholder="value"
            size={20}
          />
          <button
            type="button"
            className="preset-btn preset-btn--danger"
            disabled={conditions.length === 1}
            onClick={() => setConditions((prev) => prev.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button type="button" className="preset-btn" onClick={() => setConditions((prev) => [...prev, emptyCondition()])}>
        + Add condition
      </button>

      <p className="reply-draft-card__label" style={{ marginTop: 12 }}>
        Then force (set at least one)
      </p>
      <div className="override-form-row">
        <select value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">Department: don't change</option>
          {DEPARTMENTS.map((d) => (
            <option key={d} value={d}>
              Department: {d}
            </option>
          ))}
        </select>
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">Action: don't change</option>
          {ROUTING_ACTIONS.map((a) => (
            <option key={a} value={a}>
              Action: {a}
            </option>
          ))}
        </select>
        <select value={review} onChange={(e) => setReview(e.target.value)}>
          {REVIEW_CHOICES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <div className="reply-draft-card__actions">
        <button type="button" className="preset-btn preset-btn--active" disabled={!canSubmit || create.isPending} onClick={handleSubmit}>
          Create override
        </button>
      </div>
      {create.isError && <p className="state-message state-message--error">{(create.error as Error).message}</p>}
    </div>
  );
}

export function RoutingRulesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const query = useRoutingOverrides();
  const { toggleActive, remove } = useRoutingOverrideMutations();

  return (
    <div>
      <h2>Routing Rules</h2>
      <p className="page-note">
        Admin-configured overrides layered on top of the automatic routing engine: if an override's conditions match,
        it forces the department, action, and/or human-review flag it names -- the underlying model-driven routing
        decision is never replaced, only overridden. A high-impact department (HR, Legal, Billing) always requires
        human review regardless of any override.
        {!isAdmin && " You can view the current rules below; only an organization admin can add, toggle, or remove one."}
      </p>
      <QueryState query={query}>
        {(data) =>
          data.overrides.length === 0 ? (
            <div className="state-message">No routing overrides configured -- every email is routed by the model-driven engine alone.</div>
          ) : (
            <table className="data-table" style={{ marginBottom: 20 }}>
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Name</th>
                  <th>Conditions</th>
                  <th>Forces</th>
                  <th>Active</th>
                  {isAdmin && <th></th>}
                </tr>
              </thead>
              <tbody>
                {[...data.overrides]
                  .sort((a, b) => a.priority_order - b.priority_order)
                  .map((o) => (
                    <tr key={o.id}>
                      <td>{o.priority_order}</td>
                      <td>{o.name}</td>
                      <td>{o.conditions.map(describeCondition).join(" AND ")}</td>
                      <td>
                        {[
                          o.override_department && `department=${o.override_department}`,
                          o.override_action && `action=${o.override_action}`,
                          o.override_requires_human_review !== null && `requires_human_review=${o.override_requires_human_review}`,
                        ]
                          .filter(Boolean)
                          .join(", ")}
                      </td>
                      <td>
                        {isAdmin ? (
                          <input
                            type="checkbox"
                            checked={o.is_active}
                            onChange={(e) => toggleActive.mutate({ id: o.id, isActive: e.target.checked })}
                          />
                        ) : (
                          <span>{o.is_active ? "Yes" : "No"}</span>
                        )}
                      </td>
                      {isAdmin && (
                        <td>
                          <button type="button" className="preset-btn preset-btn--danger" onClick={() => remove.mutate(o.id)}>
                            Delete
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
              </tbody>
            </table>
          )
        }
      </QueryState>

      {isAdmin && <NewOverrideForm />}
    </div>
  );
}
