import { useState } from "react";
import { useMarkNotificationsRead, useNotifications } from "../hooks/useAdmin";

// FR-18 in-app notifications (critical emails, SLA at risk/breached,
// drift, retraining results).
export function NotificationBell() {
  const query = useNotifications();
  const markRead = useMarkNotificationsRead();
  const [open, setOpen] = useState(false);
  const unread = query.data?.unread_count ?? 0;

  return (
    <div className="notification-bell">
      <button
        type="button"
        className={unread > 0 ? "preset-btn preset-btn--active" : "preset-btn"}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Notifications{unread > 0 ? ` (${unread})` : ""}
      </button>
      {open && (
        <div className="notification-panel" role="dialog" aria-label="Notifications">
          <div className="notification-panel__header">
            <strong>Notifications</strong>
            <button
              type="button"
              className="preset-btn"
              disabled={unread === 0 || markRead.isPending}
              onClick={() => markRead.mutate()}
            >
              Mark all read
            </button>
          </div>
          {query.isError && <div className="state-message state-message--error">Could not load notifications.</div>}
          {query.data?.notifications.length === 0 && <div className="state-message">Nothing yet.</div>}
          <ul className="notification-list">
            {query.data?.notifications.map((n) => (
              <li
                key={n.id}
                className={`notification-item notification-item--${n.severity}${n.is_read ? "" : " notification-item--unread"}`}
              >
                <div className="notification-item__title">{n.title}</div>
                {n.message && <div className="notification-item__message">{n.message}</div>}
                <div className="notification-item__meta">
                  {new Date(n.created_at).toLocaleString()}
                  {n.webhook_status !== "not_configured" && ` · webhook ${n.webhook_status}`}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
