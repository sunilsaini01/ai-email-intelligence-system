import { NavLink, Outlet } from "react-router-dom";
import { DateRangePicker } from "./DateRangePicker";
import { useAuth } from "../hooks/useAuth";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/email-volume", label: "Email Volume" },
  { to: "/categories", label: "Categories" },
  { to: "/sentiment", label: "Sentiment" },
  { to: "/priority", label: "Priority" },
  { to: "/sla", label: "SLA" },
  { to: "/agents", label: "Agent Workload" },
  { to: "/models", label: "Model Quality" },
  { to: "/review-queue", label: "Human Review Queue" },
  { to: "/reply-drafts", label: "Reply Drafts" },
  { to: "/routing-rules", label: "Routing Rules" },
  { to: "/reports", label: "Reports" },
];

export function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1 className="sidebar__title">Email Intelligence</h1>
        <p className="sidebar__subtitle">Manager Dashboard</p>
        <nav>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link nav-link--active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          <span className="sidebar__user" title={user?.email}>
            {user?.email}
          </span>
          <button type="button" className="preset-btn" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <DateRangePicker />
        <div className="page-body">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
