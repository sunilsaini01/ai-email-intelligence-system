import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { acceptInvitation, registerOrganization } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.detail as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{loc: [..., "email"], msg: "..."}]. Show
    // the server's own reason (e.g. a rejected email domain) instead of
    // guessing that the password was the problem.
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { loc?: unknown[]; msg?: string };
      const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "form";
      return `Please check the ${field}: ${first.msg ?? "invalid value"}`;
    }
  }
  return "Something went wrong -- is the API reachable?";
}

function AuthForm({
  title,
  subtitle,
  submitLabel,
  onSubmit,
  children,
}: {
  title: string;
  subtitle: string;
  submitLabel: string;
  onSubmit: (email: string, password: string) => Promise<void>;
  children?: ReactNode;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-form" onSubmit={handleSubmit}>
        <h1 className="sidebar__title">{title}</h1>
        <p className="sidebar__subtitle">{subtitle}</p>
        {children}
        <label className="login-field">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="login-field">
          Password (8+ characters)
          <input type="password" value={password} minLength={8} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="state-message state-message--error login-error">{error}</p>}
        <button type="submit" className="preset-btn preset-btn--active" disabled={isSubmitting}>
          {isSubmitting ? "Working…" : submitLabel}
        </button>
        <p className="page-note">
          <Link to="/login">Back to sign in</Link>
        </p>
      </form>
    </div>
  );
}

// Public signup: always a brand-new organization, creator becomes admin.
export function CreateOrganizationPage() {
  const { login } = useAuth();
  const [organizationName, setOrganizationName] = useState("");

  return (
    <AuthForm
      title="Create an organization"
      subtitle="You'll be its admin. To join an existing organization, ask its admin for an invitation link."
      submitLabel="Create organization"
      onSubmit={async (email, password) => {
        await registerOrganization(email, password, organizationName);
        await login(email, password);
      }}
    >
      <label className="login-field">
        Organization name
        <input value={organizationName} onChange={(e) => setOrganizationName(e.target.value)} required autoFocus />
      </label>
    </AuthForm>
  );
}

// Invitation links carry the token in the URL fragment (#token=...), which
// browsers never send to the server.
export function AcceptInvitationPage() {
  const { login } = useAuth();
  const location = useLocation();
  const token = new URLSearchParams(location.hash.replace(/^#/, "")).get("token") ?? "";

  if (!token) {
    return (
      <div className="login-page">
        <div className="login-form">
          <p className="state-message state-message--error">
            This invitation link is incomplete. Ask your admin to send it again.
          </p>
          <Link to="/login">Back to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <AuthForm
      title="Join your organization"
      subtitle="Use the email address the invitation was sent to."
      submitLabel="Accept invitation"
      onSubmit={async (email, password) => {
        await acceptInvitation(token, email, password);
        await login(email, password);
      }}
    />
  );
}
