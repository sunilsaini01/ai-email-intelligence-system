import { useEffect, useState } from "react";
import { QueryState } from "../components/QueryState";
import {
  useAdminUsers,
  useCategoryTaxonomy,
  useCreateInvitation,
  useInvitations,
  useRevokeInvitation,
  useEraseSubject,
  useHasRole,
  useOrganizationSettings,
  useUpdateAdminUser,
  useUpdateCategoryTaxonomy,
  useUpdateOrganizationSettings,
} from "../hooks/useAdmin";
import { useAuth } from "../hooks/useAuth";
import {
  ASSIGNMENT_STRATEGIES,
  USER_ROLES,
  type AdminUser,
  type AssignmentStrategy,
  type CategoryTaxonomyEntry,
  type OrganizationSettings,
  type UserRole,
} from "../types/admin";
import { DEPARTMENTS } from "../types/routingOverrides";

function errorText(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function SettingsForm({ settings }: { settings: OrganizationSettings }) {
  const update = useUpdateOrganizationSettings();
  const [webhook, setWebhook] = useState(settings.notification_webhook_url ?? "");
  const [retention, setRetention] = useState(settings.data_retention_days?.toString() ?? "");
  const [strategy, setStrategy] = useState<AssignmentStrategy>(settings.assignment_strategy);
  const [notifyCritical, setNotifyCritical] = useState(settings.notify_on_critical);
  const [notifySla, setNotifySla] = useState(settings.notify_on_sla_at_risk);
  const [weekly, setWeekly] = useState(settings.weekly_reports_enabled);

  function save() {
    update.mutate({
      ...(webhook.trim() ? { notification_webhook_url: webhook.trim() } : { clear_webhook: true }),
      ...(retention.trim() ? { data_retention_days: Number(retention) } : { clear_retention: true }),
      assignment_strategy: strategy,
      notify_on_critical: notifyCritical,
      notify_on_sla_at_risk: notifySla,
      weekly_reports_enabled: weekly,
    });
  }

  const thresholds = Object.entries(settings.routing_thresholds);

  return (
    <section className="admin-section">
      <h3>Organization settings</h3>
      <div className="override-form-row">
        <label className="filter-field">
          Notification webhook URL (FR-18)
          <input value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://hooks.slack.com/…" />
        </label>
        <label className="filter-field">
          Agent assignment (FR-42)
          <select value={strategy} onChange={(e) => setStrategy(e.target.value as AssignmentStrategy)}>
            {ASSIGNMENT_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="filter-field">
          Data retention, days (blank = keep)
          <input type="number" min={1} value={retention} onChange={(e) => setRetention(e.target.value)} />
        </label>
      </div>
      <div className="toggle-row">
        <label>
          <input type="checkbox" checked={notifyCritical} onChange={(e) => setNotifyCritical(e.target.checked)} /> Notify
          on Critical emails
        </label>
        <label>
          <input type="checkbox" checked={notifySla} onChange={(e) => setNotifySla(e.target.checked)} /> Notify on SLA
          at risk / breached
        </label>
        <label>
          <input type="checkbox" checked={weekly} onChange={(e) => setWeekly(e.target.checked)} /> Generate weekly
          reports
        </label>
      </div>
      <button type="button" className="preset-btn preset-btn--active" disabled={update.isPending} onClick={save}>
        {update.isPending ? "Saving…" : "Save settings"}
      </button>
      {update.isSuccess && <span className="page-note"> Saved.</span>}
      {errorText(update.error) && <div className="state-message state-message--error">{errorText(update.error)}</div>}
      <p className="page-note">
        Learned auto-route thresholds (FR-41, from routing feedback; default 0.55):{" "}
        {thresholds.length === 0 ? "none yet" : thresholds.map(([d, t]) => `${d} ${t.toFixed(2)}`).join(", ")}
      </p>
    </section>
  );
}

function TaxonomyEditor({ categories, note }: { categories: CategoryTaxonomyEntry[]; note: string }) {
  const update = useUpdateCategoryTaxonomy();
  const [rows, setRows] = useState(categories);
  useEffect(() => setRows(categories), [categories]);

  const patch = (label: string, change: Partial<CategoryTaxonomyEntry>) =>
    setRows((prev) => prev.map((r) => (r.label === label ? { ...r, ...change } : r)));

  return (
    <section className="admin-section">
      <h3>Category taxonomy (FR-23)</h3>
      <p className="page-note">{note}</p>
      <table className="data-table">
        <thead>
          <tr>
            <th>Model label</th>
            <th>Display name</th>
            <th>Enabled</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td>
                <input value={r.display_name} onChange={(e) => patch(r.label, { display_name: e.target.value })} />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={r.enabled}
                  disabled={!r.can_disable}
                  onChange={(e) => patch(r.label, { enabled: e.target.checked })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="preset-btn preset-btn--active"
        disabled={update.isPending}
        onClick={() =>
          update.mutate(
            rows.map((r) => ({
              label: r.label,
              display_name: r.display_name === r.label ? null : r.display_name,
              enabled: r.enabled,
            })),
          )
        }
      >
        Save taxonomy
      </button>
      {errorText(update.error) && <div className="state-message state-message--error">{errorText(update.error)}</div>}
    </section>
  );
}

function UserRow({ user, isSelf }: { user: AdminUser; isSelf: boolean }) {
  const update = useUpdateAdminUser();
  const [skills, setSkills] = useState(user.skills.join(", "));

  return (
    <tr>
      <td>{user.email}</td>
      <td>
        <select
          value={user.role}
          disabled={isSelf}
          onChange={(e) => update.mutate({ id: user.id, update: { role: e.target.value as UserRole } })}
        >
          {USER_ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </td>
      <td>
        <select
          value={user.department ?? ""}
          onChange={(e) =>
            update.mutate({
              id: user.id,
              update: e.target.value ? { department: e.target.value } : { clear_department: true },
            })
          }
        >
          <option value="">—</option>
          {DEPARTMENTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          value={skills}
          placeholder="Refund, Complaint, Billing"
          onChange={(e) => setSkills(e.target.value)}
          onBlur={() =>
            update.mutate({ id: user.id, update: { skills: skills.split(",").map((s) => s.trim()).filter(Boolean) } })
          }
        />
      </td>
      <td>
        <input
          type="checkbox"
          checked={user.is_active}
          disabled={isSelf}
          onChange={(e) => update.mutate({ id: user.id, update: { is_active: e.target.checked } })}
        />
      </td>
      <td>
        {user.membership_source === "legacy_unverified" ? (
          <>
            ⚠ unverified (legacy){" "}
            <button
              type="button"
              className="preset-btn"
              onClick={() => update.mutate({ id: user.id, update: { confirm_membership: true } })}
            >
              Confirm
            </button>
          </>
        ) : (
          user.membership_source.replace("_", " ")
        )}
      </td>
      <td>{user.last_assigned_at ? new Date(user.last_assigned_at).toLocaleString() : "—"}</td>
      {errorText(update.error) && <td className="state-message--error">{errorText(update.error)}</td>}
    </tr>
  );
}

// Membership security fix: the only way to add someone to this
// organization. No email is sent -- the admin copies the link to the invitee.
function Invitations() {
  const query = useInvitations(true);
  const create = useCreateInvitation();
  const revoke = useRevokeInvitation();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("agent");
  const link = create.data ? `${window.location.origin}${create.data.accept_path}` : null;

  return (
    <section className="admin-section">
      <h3>Invitations</h3>
      <p className="page-note">
        People can only join this organization through an invitation: bound to one email address, single-use, and
        expiring after 72 hours. Copy the link below and send it to them yourself -- it is shown only once.
      </p>
      <div className="override-form-row">
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@example.com" />
        <select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
          {USER_ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="preset-btn preset-btn--active"
          disabled={!email.includes("@") || create.isPending}
          onClick={() => create.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail("") })}
        >
          Create invitation
        </button>
      </div>
      {link && (
        <p className="page-note">
          Invitation link for {create.data?.email}: <code>{link}</code>
        </p>
      )}
      {errorText(create.error) && <div className="state-message state-message--error">{errorText(create.error)}</div>}
      <QueryState query={query}>
        {(data) =>
          data.invitations.length === 0 ? null : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Expires</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.invitations.map((inv) => (
                  <tr key={inv.id}>
                    <td>{inv.email}</td>
                    <td>{inv.role}</td>
                    <td>{inv.status}</td>
                    <td>{new Date(inv.expires_at).toLocaleString()}</td>
                    <td>
                      {inv.status === "pending" && (
                        <button type="button" className="preset-btn" onClick={() => revoke.mutate(inv.id)}>
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </QueryState>
    </section>
  );
}

function PrivacyErasure() {
  const erase = useEraseSubject();
  const [email, setEmail] = useState("");

  function submit() {
    if (!window.confirm(`Permanently delete every stored email and prediction from ${email}? This cannot be undone.`)) {
      return;
    }
    erase.mutate(email.trim());
  }

  return (
    <section className="admin-section">
      <h3>GDPR right to deletion</h3>
      <p className="page-note">
        Erases every stored email from this sender address, its predictions, reply drafts, notifications and logged
        corrections. Permanent.
      </p>
      <div className="override-form-row">
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sender@example.com" />
        <button
          type="button"
          className="preset-btn preset-btn--danger"
          disabled={!email.includes("@") || erase.isPending}
          onClick={submit}
        >
          Erase data
        </button>
      </div>
      {erase.data && (
        <p className="page-note">
          Erased: {Object.entries(erase.data.deleted).map(([k, v]) => `${k} ${v}`).join(", ")}
        </p>
      )}
      {errorText(erase.error) && <div className="state-message state-message--error">{errorText(erase.error)}</div>}
    </section>
  );
}

export function AdminPage() {
  const { user } = useAuth();
  const isAdmin = useHasRole("admin");
  const isManager = useHasRole("manager");
  const settings = useOrganizationSettings(isManager);
  const taxonomy = useCategoryTaxonomy();
  const users = useAdminUsers(isAdmin);

  if (!isManager) {
    return <div className="state-message">Administration is available to managers and admins.</div>;
  }

  return (
    <div>
      <h2>Administration</h2>
      {!isAdmin && <p className="page-note">Read-only: changes require an admin.</p>}
      <QueryState query={settings}>{(data) => (isAdmin ? <SettingsForm settings={data} /> : null)}</QueryState>
      {isAdmin && (
        <QueryState query={taxonomy}>{(data) => <TaxonomyEditor categories={data.categories} note={data.note} />}</QueryState>
      )}
      {isAdmin && (
        <section className="admin-section">
          <h3>Users, roles and skills (RBAC, FR-42)</h3>
          <QueryState query={users}>
            {(data) => (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Department</th>
                    <th>Skills</th>
                    <th>Active</th>
                    <th>Membership</th>
                    <th>Last assigned</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <UserRow key={u.id} user={u} isSelf={u.id === user?.id} />
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
        </section>
      )}
      {isAdmin && <Invitations />}
      {isAdmin && <PrivacyErasure />}
    </div>
  );
}
