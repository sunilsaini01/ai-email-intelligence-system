"""
Weekly analytics report export -- CSV and PDF (Module 11 / Phase 11,
FR-56).

`reportlab` (not `weasyprint`) was chosen specifically because it is pure
Python with no native system libraries to install -- `weasyprint` needs
Pango/Cairo, notoriously painful on the Windows dev environment this
project targets. See docs/architecture_dashboard.md "PDF library".

This is an on-demand export endpoint, not a scheduled job -- "auto-
generated weekly" per FR-56's literal wording would need a
scheduler/cron dependency this codebase does not have; building one was
explicitly out of scope rather than silently narrowing FR-56's actual
requirement. See docs/requirements_traceability_phase11.md.

Every report carries the SAME evidence labels the live dashboard does
(docs/architecture_dashboard.md "Model evidence policy") -- a PDF must
not present synthetic/unvalidated metrics as validated just because it
looks like a formal document.
"""

import csv
import io

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import dashboard_service
from app.services.dashboard_service import DateRange


async def build_report_data(db: AsyncSession, organization_id: str, date_range: DateRange) -> dict:
    return {
        "overview": await dashboard_service.get_overview(db, organization_id, date_range),
        "email_volume": await dashboard_service.get_email_volume(db, organization_id, date_range),
        "categories": await dashboard_service.get_category_distribution(db, organization_id, date_range),
        "sentiment": await dashboard_service.get_sentiment_trend(db, organization_id, date_range),
        "priority": await dashboard_service.get_priority_distribution(db, organization_id, date_range),
        "sla": await dashboard_service.get_sla(db, organization_id, date_range),
        "agents": await dashboard_service.get_agent_workload(db, organization_id, date_range),
        "models": await dashboard_service.get_model_quality(db, organization_id, date_range),
    }


def export_csv(data: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    overview = data["overview"]
    writer.writerow(["== Overview =="])
    for key, value in overview.items():
        writer.writerow([key, value])
    writer.writerow([])

    writer.writerow(["== Email Volume =="])
    writer.writerow(["bucket", "count"])
    for point in data["email_volume"]["points"]:
        writer.writerow([point["bucket"], point["count"]])
    writer.writerow([])

    writer.writerow(["== Categories ==", f"evidence: {data['categories']['evidence']['status']}"])
    writer.writerow(["category", "count"])
    for row in data["categories"]["counts"]:
        writer.writerow([row["category"], row["count"]])
    writer.writerow([])

    writer.writerow(["== Sentiment ==", f"evidence: {data['sentiment']['evidence']['status']}"])
    writer.writerow(["bucket", "sentiment", "count"])
    for row in data["sentiment"]["points"]:
        writer.writerow([row["bucket"], row["sentiment"], row["count"]])
    writer.writerow([])

    writer.writerow(["== Priority ==", f"evidence: {data['priority']['evidence']['status']}"])
    writer.writerow(["priority", "count"])
    for row in data["priority"]["counts"]:
        writer.writerow([row["priority"], row["count"]])
    writer.writerow([])

    writer.writerow(["== SLA ==", data["sla"]["note"]])
    writer.writerow(["priority", "within_sla", "at_risk", "breached"])
    for row in data["sla"]["buckets"]:
        writer.writerow([row["priority"], row["within_sla"], row["at_risk"], row["breached"]])
    writer.writerow(["excluded_no_priority", data["sla"]["excluded_no_priority"]])
    writer.writerow([])

    writer.writerow(["== Agent Workload ==", data["agents"]["note"]])
    writer.writerow(["reviewer_id", "assigned", "pending", "resolved", "avg_resolution_minutes"])
    for row in data["agents"]["agents"]:
        writer.writerow([row["reviewer_id"], row["assigned"], row["pending"], row["resolved"], row["avg_resolution_minutes"]])
    writer.writerow([])

    writer.writerow(["== Model Quality =="])
    writer.writerow(["module", "evidence_status", "offline_reference_metric", "correction_rate", "reviewed_count", "corrected_count"])
    for row in data["models"]["modules"]:
        writer.writerow(
            [
                row["module"],
                row["evidence"]["status"],
                row["offline_reference_metric"],
                row["correction_rate"],
                row["reviewed_count"],
                row["corrected_count"],
            ]
        )

    return buffer.getvalue()


def export_pdf(data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("AI Email Intelligence System -- Weekly Analytics Report", styles["Title"]))
    overview = data["overview"]
    elements.append(Paragraph(f"Range: {overview['date_range_start']} to {overview['date_range_end']}", styles["Normal"]))
    elements.append(Paragraph(overview["note"], styles["Italic"]))
    elements.append(Spacer(1, 12))

    def _table(title: str, header: list[str], rows: list[list], note: str | None = None) -> None:
        elements.append(Paragraph(title, styles["Heading2"]))
        if note:
            elements.append(Paragraph(note, styles["Italic"]))
        table_data = [header] + [[str(cell) for cell in row] for row in rows]
        table = Table(table_data, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(table)
        elements.append(Spacer(1, 12))

    _table(
        "Executive Overview",
        ["Metric", "Value"],
        [
            ["Total emails (proxy)", overview["total_emails_proxy"]],
            ["Emails/day (avg)", overview["emails_per_day_avg"]],
            ["Spam rate", overview["spam_rate"]],
            ["High/Critical priority count", overview["high_critical_priority_count"]],
            ["SLA breach count", overview["sla_breach_count"]],
            ["Pending human reviews", overview["pending_human_reviews"]],
            ["Feedback correction rate", overview["feedback_correction_rate"] if overview["reviewed_feedback_count"] else "No real observations yet"],
            ["Auto-Reply acceptance rate", overview["auto_reply_acceptance_rate"] if overview["auto_reply_reviewed_count"] else "No real observations yet"],
        ],
    )

    _table("Categories", ["Category", "Count"], [[r["category"], r["count"]] for r in data["categories"]["counts"]], note=f"Evidence: {data['categories']['evidence']['status']} -- {data['categories']['evidence']['note']}")
    _table("Priority", ["Priority", "Count"], [[r["priority"], r["count"]] for r in data["priority"]["counts"]], note=f"Evidence: {data['priority']['evidence']['status']}")
    _table(
        "SLA",
        ["Priority", "Within SLA", "At Risk", "Breached"],
        [[r["priority"], r["within_sla"], r["at_risk"], r["breached"]] for r in data["sla"]["buckets"]],
        note=data["sla"]["note"],
    )
    _table(
        "Model Quality",
        ["Module", "Evidence", "Correction Rate", "Reviewed"],
        [
            [
                r["module"],
                r["evidence"]["status"],
                r["correction_rate"] if r["reviewed_count"] else "No real observations yet",
                r["reviewed_count"],
            ]
            for r in data["models"]["modules"]
        ],
    )

    doc.build(elements)
    return buffer.getvalue()
