"""
Periodic jobs run by the agents process (app/agents/runner.py) -- the
"scheduler" earlier phases noted this codebase lacked (Phase 11's
"no scheduled report generation", Phase 12's stuck-workflow note).

Each job is one pass over every known organization; runner.py loops it
on its own interval. They live in the agents process, not the API,
because that process is a single replica (k8s/agents-deployment.yaml):
a job running in each of N API replicas would fire N times.

  - sla_sweep           PRD Epic 2: alert BEFORE an SLA breach
  - drift_check         FR-72: model drift gauges + alert notification
  - run_retraining      FR-61: execute pending retraining triggers
  - generate_weekly_reports  FR-56
  - purge_retention     PRD SS6.4 GDPR retention
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.metrics import MODEL_CORRECTION_RATE, MODEL_PREDICTION_DRIFT_PSI, SLA_EMAILS
from app.mlops.retraining_runner import run_next_trigger
from app.models.email_record import EmailRecord
from app.models.generated_report import GeneratedReport
from app.models.notification import KIND_MODEL_DRIFT, KIND_SLA_AT_RISK, KIND_SLA_BREACHED
from app.models.organization_settings import OrganizationSettings
from app.models.user import User
from app.retrieval.resolution_status import CLOSED, RESOLVED
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID
from app.services import dashboard_service
from app.services.dashboard_report_export import build_report_data, export_csv, export_pdf
from app.services.drift_service import compute_drift
from app.services.notification_service import notify, safe_subject
from app.services.organization_settings_service import get_org_settings
from app.services.privacy_service import purge_expired_data

logger = logging.getLogger("app.scheduled_jobs")

# Open emails older than this are left to the SLA dashboard; the sweep's
# job is catching emails as they cross into at-risk, not re-scanning
# the whole history every few minutes.
SLA_SWEEP_LOOKBACK_DAYS = 14


async def known_organizations(session: AsyncSession) -> list[str]:
    orgs = {DEFAULT_ORGANIZATION_ID}
    for column in (User.organization_id, OrganizationSettings.organization_id, EmailRecord.organization_id):
        orgs.update(row[0] for row in (await session.execute(select(column).distinct())).all() if row[0])
    return sorted(orgs)


async def sla_sweep(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    totals = {
        dashboard_service.SLA_WITHIN: 0,
        dashboard_service.SLA_AT_RISK: 0,
        dashboard_service.SLA_BREACHED: 0,
    }
    for organization_id in await known_organizations(session):
        org_settings = await get_org_settings(session, organization_id)
        rows = (
            await session.execute(
                select(EmailRecord).where(
                    EmailRecord.organization_id == organization_id,
                    EmailRecord.is_deleted == False,  # noqa: E712
                    EmailRecord.resolution_status.not_in((RESOLVED, CLOSED)),
                    EmailRecord.priority.is_not(None),
                    EmailRecord.received_at >= now - timedelta(days=SLA_SWEEP_LOOKBACK_DAYS),
                )
            )
        ).scalars()
        for email in rows:
            state = dashboard_service.classify_sla(email.priority, email.received_at, email.resolved_at, now)
            if state is None:
                continue
            totals[state] += 1
            if state == dashboard_service.SLA_WITHIN or not org_settings["notify_on_sla_at_risk"]:
                continue
            kind = KIND_SLA_AT_RISK if state == dashboard_service.SLA_AT_RISK else KIND_SLA_BREACHED
            target = dashboard_service.sla_targets_hours()[email.priority]
            await notify(
                session,
                organization_id,
                kind=kind,
                title=f"SLA {'at risk' if kind == KIND_SLA_AT_RISK else 'breached'}: {safe_subject(email.subject)}",
                message=f"{email.priority} email, {target:g}h SLA, department {email.department or 'unassigned'}.",
                severity="warning" if kind == KIND_SLA_AT_RISK else "critical",
                email_id=email.id,
                dedup_key=f"{kind}:{email.id}",
                payload={"priority": email.priority, "department": email.department},
            )
    for state, count in totals.items():
        SLA_EMAILS.labels(state=state).set(count)
    return totals


async def drift_check(session: AsyncSession) -> list[dict]:
    """Gauges are exported for the default organization only -- the
    models are shared across organizations, and per-org label series
    would be unbounded Prometheus cardinality (docs/architecture/
    architecture_monitoring.md "Label Cardinality"). Notifications go to
    every organization whose own traffic drifted."""
    reports: list[dict] = []
    for organization_id in await known_organizations(session):
        for drift in await compute_drift(session, organization_id):
            if organization_id == DEFAULT_ORGANIZATION_ID:
                MODEL_PREDICTION_DRIFT_PSI.labels(module=drift.module).set(drift.psi if drift.psi is not None else -1)
                for window, rate in (
                    ("current", drift.current_correction_rate),
                    ("baseline", drift.baseline_correction_rate),
                ):
                    MODEL_CORRECTION_RATE.labels(module=drift.module, window=window).set(
                        rate if rate is not None else -1
                    )
            if drift.alert:
                week = datetime.now(UTC).strftime("%G-W%V")
                await notify(
                    session,
                    organization_id,
                    kind=KIND_MODEL_DRIFT,
                    title=f"Model drift detected: {drift.module}",
                    message=(
                        f"Prediction PSI {drift.psi} ({drift.prediction_status}); correction rate "
                        f"{drift.baseline_correction_rate} -> {drift.current_correction_rate}."
                    ),
                    severity="warning",
                    dedup_key=f"{KIND_MODEL_DRIFT}:{drift.module}:{week}",
                    payload=drift.as_dict(),
                )
            reports.append({"organization_id": organization_id, **drift.as_dict()})
    return reports


async def run_retraining(session: AsyncSession) -> int:
    ran = 0
    while await run_next_trigger(session) is not None:
        ran += 1
    return ran


def previous_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 UTC to the following Monday 00:00 UTC, for the most
    recent fully-completed week."""
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return this_monday - timedelta(days=7), this_monday


async def generate_weekly_reports(session: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    if now.weekday() != get_settings().WEEKLY_REPORT_WEEKDAY:
        return 0
    start, end = previous_week_bounds(now)
    generated = 0
    for organization_id in await known_organizations(session):
        if not (await get_org_settings(session, organization_id))["weekly_reports_enabled"]:
            continue
        existing = await session.execute(
            select(GeneratedReport.id).where(
                GeneratedReport.organization_id == organization_id, GeneratedReport.period_start == start
            )
        )
        if existing.first() is not None:
            continue
        data = await build_report_data(
            session, organization_id, dashboard_service.DateRange(start=start, end=end - timedelta(microseconds=1))
        )
        session.add_all(
            [
                GeneratedReport(
                    organization_id=organization_id,
                    period_start=start,
                    period_end=end,
                    report_format="csv",
                    content=export_csv(data).encode("utf-8"),
                ),
                GeneratedReport(
                    organization_id=organization_id,
                    period_start=start,
                    period_end=end,
                    report_format="pdf",
                    content=export_pdf(data),
                ),
            ]
        )
        await session.commit()
        generated += 1
        logger.info("weekly_report_generated", extra={"organization_id": organization_id, "period_start": start.isoformat()})
    return generated


async def purge_retention(session: AsyncSession) -> dict[str, dict]:
    purged: dict[str, dict] = {}
    for organization_id in await known_organizations(session):
        days = (await get_org_settings(session, organization_id))["data_retention_days"]
        if days:
            purged[organization_id] = await purge_expired_data(session, organization_id, int(days))
    return purged
