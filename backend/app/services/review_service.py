"""Human-in-the-Loop Handover Report Review Service.

Provides finding-level human review workflows: accept, reject, edit, and flag
for investigation, with immutable review decision history and report finalization gates.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.database import get_db_context
from app.schemas.analysis import (
    CreateReviewDecisionRequest,
    FindingUpdatePayload,
    ReportReviewStatus,
    ReviewDecisionRecord,
    ReviewDecisionType,
    ReviewSummary,
)

logger = logging.getLogger("relaypoint.review_service")


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    """Generate unique prefixed identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def normalize_report_status(status_str: Optional[str]) -> str:
    """Normalize legacy 'draft' status to standard 'pending_review'."""
    if not status_str or status_str in ("draft", "pending_review"):
        return ReportReviewStatus.PENDING_REVIEW.value
    if status_str == "in_review":
        return ReportReviewStatus.IN_REVIEW.value
    if status_str == "finalized":
        return ReportReviewStatus.FINALIZED.value
    return status_str


def _update_finding_in_list(finding_list: List[Dict[str, Any]], updated: Dict[str, Any]) -> None:
    """In-place update of finding dictionaries matching ID."""
    for idx, item in enumerate(finding_list):
        if isinstance(item, dict) and item.get("id") == updated.get("id"):
            finding_list[idx] = dict(updated)


def _sync_finding_across_views(report_payload: Dict[str, Any], finding: Dict[str, Any]) -> None:
    """Propagate updated finding data into Developer View and Team Lead View collections."""
    # 1. Update in raw_findings
    if "raw_findings" in report_payload and isinstance(report_payload["raw_findings"], list):
        _update_finding_in_list(report_payload["raw_findings"], finding)

    # 2. Update in developer_view
    dev_view = report_payload.get("developer_view")
    if isinstance(dev_view, dict):
        for key in [
            "technical_architecture",
            "active_code_work",
            "unfinished_implementations",
            "blockers_and_failing_areas",
            "immediate_tasks",
        ]:
            if key in dev_view and isinstance(dev_view[key], list):
                _update_finding_in_list(dev_view[key], finding)

    # 3. Update in team_lead_view
    lead_view = report_payload.get("team_lead_view")
    if isinstance(lead_view, dict):
        for key in [
            "major_milestones_and_workstreams",
            "critical_blockers_and_risks",
            "strategic_priorities",
        ]:
            if key in lead_view and isinstance(lead_view[key], list):
                _update_finding_in_list(lead_view[key], finding)


def get_review_history_and_summary(
    report_id: str,
    report_dict: Dict[str, Any],
) -> Tuple[ReviewSummary, List[ReviewDecisionRecord]]:
    """Retrieve all review decisions from SQLite and compile aggregate progress summary."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, report_id, item_id, decision, reviewer_name, reviewer_comment,
                   created_at, original_finding_json, updated_finding_json
            FROM review_decisions
            WHERE report_id = ?
            ORDER BY created_at ASC;
            """,
            (report_id,),
        )
        rows = cursor.fetchall()

    history: List[ReviewDecisionRecord] = []
    latest_by_item: Dict[str, ReviewDecisionRecord] = {}

    for r in rows:
        r_dict = dict(r)
        orig = None
        upd = None
        try:
            if r_dict.get("original_finding_json"):
                orig = json.loads(r_dict["original_finding_json"])
        except Exception:
            orig = None

        try:
            if r_dict.get("updated_finding_json"):
                upd = json.loads(r_dict["updated_finding_json"])
        except Exception:
            upd = None

        record = ReviewDecisionRecord(
            id=r_dict["id"],
            report_id=r_dict["report_id"],
            item_id=r_dict["item_id"],
            decision=ReviewDecisionType(r_dict["decision"]) if r_dict["decision"] in [e.value for e in ReviewDecisionType] else ReviewDecisionType.ACCEPTED,
            reviewer_name=r_dict["reviewer_name"],
            reviewer_comment=r_dict.get("reviewer_comment"),
            created_at=r_dict["created_at"],
            original_finding=orig,
            updated_finding=upd,
        )
        history.append(record)
        # Exclude report-level finalization records from item counts
        if record.item_id != "REPORT_FINALIZATION":
            latest_by_item[record.item_id] = record

    # Extract all findings in report
    payload = report_dict.get("report_data")
    if not payload and "report_json" in report_dict:
        try:
            payload = json.loads(report_dict["report_json"])
        except Exception:
            payload = {}
    elif not payload:
        payload = {}

    raw_findings = payload.get("raw_findings", [])
    total_findings = len(raw_findings)
    reviewed_count = len(latest_by_item)
    pending_count = max(0, total_findings - reviewed_count)

    accepted_count = sum(1 for rec in latest_by_item.values() if rec.decision == ReviewDecisionType.ACCEPTED)
    rejected_count = sum(1 for rec in latest_by_item.values() if rec.decision == ReviewDecisionType.REJECTED)
    edited_count = sum(1 for rec in latest_by_item.values() if rec.decision == ReviewDecisionType.EDITED)
    needs_inv_count = sum(1 for rec in latest_by_item.values() if rec.decision == ReviewDecisionType.NEEDS_INVESTIGATION)

    db_status = normalize_report_status(report_dict.get("status"))
    if db_status == ReportReviewStatus.FINALIZED.value:
        report_review_status = ReportReviewStatus.FINALIZED.value
    elif reviewed_count > 0:
        report_review_status = ReportReviewStatus.IN_REVIEW.value
    else:
        report_review_status = ReportReviewStatus.PENDING_REVIEW.value

    can_finalize = (
        report_review_status != ReportReviewStatus.FINALIZED.value
        and total_findings > 0
        and reviewed_count == total_findings
    )

    summary = ReviewSummary(
        total_findings=total_findings,
        reviewed_count=reviewed_count,
        pending_count=pending_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        edited_count=edited_count,
        needs_investigation_count=needs_inv_count,
        report_review_status=report_review_status,
        can_finalize=can_finalize,
        latest_decisions=latest_by_item,
    )

    return summary, history


def record_review_decision(report_id: str, payload: CreateReviewDecisionRequest) -> ReviewDecisionRecord:
    """Record a human reviewer's decision on a finding, preserving original AI findings."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM handover_reports WHERE id = ?;", (report_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Handover report '{report_id}' not found.")

        report = dict(row)
        current_status = normalize_report_status(report.get("status"))
        if current_status == ReportReviewStatus.FINALIZED.value:
            raise ValueError("Report is finalized. Decisions cannot be added or modified on a finalized report.")

        try:
            report_data = json.loads(report.get("report_json", "{}"))
        except Exception as json_err:
            raise ValueError(f"Malformed report payload: {json_err}") from json_err

        raw_findings = report_data.get("raw_findings", [])
        target_finding = next((f for f in raw_findings if f.get("id") == payload.finding_id), None)
        if not target_finding:
            raise ValueError(f"Finding '{payload.finding_id}' was not found in report '{report_id}'.")

        # 1. Guarantee immutable preservation of original AI findings
        if "original_findings" not in report_data or not report_data["original_findings"]:
            report_data["original_findings"] = [dict(f) for f in raw_findings]

        original_snapshot = next(
            (of for of in report_data["original_findings"] if of.get("id") == payload.finding_id),
            dict(target_finding),
        )

        # 2. Process edits if decision is 'edited'
        updated_snapshot = None
        now = _now_iso()

        if payload.decision == ReviewDecisionType.EDITED:
            if not payload.updated_finding:
                raise ValueError("An 'edited' review decision requires 'updated_finding' content.")

            update_data = payload.updated_finding.model_dump(exclude_unset=True)
            for key, val in update_data.items():
                if val is not None:
                    target_finding[key] = val.value if hasattr(val, "value") else val

            target_finding["is_edited"] = True
            target_finding["original_data"] = original_snapshot
            updated_snapshot = dict(target_finding)

        # 3. Update finding review metadata
        target_finding["review_decision"] = payload.decision.value
        target_finding["review_comment"] = payload.reviewer_comment
        target_finding["reviewer_name"] = payload.reviewer_name
        target_finding["reviewed_at"] = now

        # Synchronize views
        _sync_finding_across_views(report_data, target_finding)

        # 4. Insert review decision into SQLite
        decision_id = _generate_id("dec")
        conn.execute(
            """
            INSERT INTO review_decisions (
                id, report_id, item_id, decision, reviewer_name, reviewer_comment,
                created_at, original_finding_json, updated_finding_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                decision_id,
                report_id,
                payload.finding_id,
                payload.decision.value,
                payload.reviewer_name or "Lead Reviewer (Demo)",
                payload.reviewer_comment or "",
                now,
                json.dumps(original_snapshot),
                json.dumps(updated_snapshot) if updated_snapshot else None,
            ),
        )

        # 5. Transition status to in_review if pending
        new_status = ReportReviewStatus.IN_REVIEW.value if current_status == ReportReviewStatus.PENDING_REVIEW.value else current_status
        conn.execute(
            """
            UPDATE handover_reports
            SET status = ?, report_json = ?, updated_at = ?
            WHERE id = ?;
            """,
            (new_status, json.dumps(report_data), now, report_id),
        )

    return ReviewDecisionRecord(
        id=decision_id,
        report_id=report_id,
        item_id=payload.finding_id,
        decision=payload.decision,
        reviewer_name=payload.reviewer_name or "Lead Reviewer (Demo)",
        reviewer_comment=payload.reviewer_comment or "",
        created_at=now,
        original_finding=original_snapshot,
        updated_finding=updated_snapshot,
    )


def finalize_report(
    report_id: str,
    reviewer_name: str = "Lead Reviewer (Demo)",
    final_notes: str = "",
) -> Dict[str, Any]:
    """Finalize report review, enforcing that all findings have been reviewed."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM handover_reports WHERE id = ?;", (report_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Handover report '{report_id}' not found.")

        report = dict(row)
        current_status = normalize_report_status(report.get("status"))
        if current_status == ReportReviewStatus.FINALIZED.value:
            raise ValueError("Report is already finalized.")

        try:
            report_data = json.loads(report.get("report_json", "{}"))
        except Exception as json_err:
            raise ValueError(f"Malformed report payload: {json_err}") from json_err

    # Compute review completion metrics
    summary, _ = get_review_history_and_summary(report_id, report)

    if summary.total_findings > 0 and summary.reviewed_count < summary.total_findings:
        unreviewed = summary.total_findings - summary.reviewed_count
        raise ValueError(
            f"Cannot finalize report: {unreviewed} of {summary.total_findings} finding(s) are pending review. "
            f"Every finding must be accepted, rejected, edited, or marked for investigation prior to finalization."
        )

    now = _now_iso()
    with get_db_context() as conn:
        # Record finalization milestone in review_decisions audit table
        if final_notes or reviewer_name:
            final_dec_id = _generate_id("dec")
            conn.execute(
                """
                INSERT INTO review_decisions (
                    id, report_id, item_id, decision, reviewer_name, reviewer_comment,
                    created_at, original_finding_json, updated_finding_json
                ) VALUES (?, ?, 'REPORT_FINALIZATION', 'accepted', ?, ?, ?, NULL, NULL);
                """,
                (
                    final_dec_id,
                    report_id,
                    reviewer_name,
                    final_notes or "Handover report review finalized.",
                    now,
                ),
            )

        # Update handover report status to finalized
        conn.execute(
            """
            UPDATE handover_reports
            SET status = 'finalized', updated_at = ?
            WHERE id = ?;
            """,
            (now, report_id),
        )

    logger.info("Handover report %s successfully finalized by %s", report_id, reviewer_name)
    return {
        "report_id": report_id,
        "status": ReportReviewStatus.FINALIZED.value,
        "finalized_at": now,
        "reviewer_name": reviewer_name,
        "reviewed_findings_count": summary.reviewed_count,
        "message": f"Handover report successfully finalized with {summary.reviewed_count} reviewed findings.",
    }
