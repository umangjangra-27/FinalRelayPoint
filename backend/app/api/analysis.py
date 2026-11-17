"""AI Analysis and Handover Report Generation API Endpoints."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.database import get_db_context
from app.integrations.gemini import (
    GeminiAuthError,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiQuotaError,
    GeminiResponseError,
    GeminiTimeoutError,
    GeminiUnavailableError,
)
from app.schemas.analysis import (
    AnalysisResult,
    ConfidenceLevel,
    CoverageSummary,
    CreateReviewDecisionRequest,
    FinalizeReportRequest,
    Finding,
    FindingCategory,
    PriorityLevel,
    ReportDetailResponse,
    ReportSummaryResponse,
    ReviewDecisionRecord,
    ReviewSummary,
    VerificationStatus,
)
from app.services.analyzer import RepositoryAnalyzer
from app.services.report_generator import (
    ReportGenerator,
    get_report_by_id,
    list_reports_for_repository,
    reverify_report,
)
from app.services.review_service import (
    finalize_report,
    get_review_history_and_summary,
    record_review_decision,
)

logger = logging.getLogger("relaypoint.api.analysis")

router = APIRouter(tags=["Analysis & Reports"])


def _generate_id(prefix: str) -> str:
    """Generate unique prefixed identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@router.post(
    "/repositories/{repository_id}/analyze",
    status_code=status.HTTP_201_CREATED,
    summary="Trigger AI Knowledge Synthesis and Handover Report Generation",
    description="Prepares bounded context from sanitized chunks, invokes Gemini for structured synthesis, verifies citations, and generates role-based handover reports.",
)
def analyze_repository(repository_id: str) -> Dict[str, Any]:
    """Execute end-to-end AI synthesis and evidence-linked report generation."""
    settings = get_settings()

    # 1. Verify Repository Existence
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, full_name FROM repositories WHERE id = ?;", (repository_id,))
        repo = cursor.fetchone()
        if not repo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repository_id}' not found.",
            )
        repo_name = repo["full_name"] or repo["name"]

        # 2. Verify Ingested Sources Exist
        cursor.execute("SELECT count(*) FROM source_chunks WHERE repository_id = ?;", (repository_id,))
        chunk_count = cursor.fetchone()[0]
        if chunk_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Repository has no ingested source chunks. Please run ingestion before triggering analysis.",
            )

    # 3. Check Gemini API Configuration
    analyzer = RepositoryAnalyzer()
    if not analyzer.gemini_client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GEMINI_API_KEY is not configured. Please configure your API key in environment or .env file.",
        )

    # 4. Create Analysis Run
    run_id = _generate_id("run")
    start_time = _now_iso()
    with get_db_context() as conn:
        conn.execute(
            """
            INSERT INTO analysis_runs (id, repository_id, status, started_at)
            VALUES (?, ?, 'running', ?);
            """,
            (run_id, repository_id, start_time),
        )

    try:
        # 5. Execute Structured Synthesis
        analysis_result, selected_chunks = analyzer.analyze_repository(repository_id)

        # 6. Verify Evidence & Persist Report
        generator = ReportGenerator(repository_id)
        report_meta = generator.assemble_and_persist_report(
            analysis=analysis_result,
            analysis_run_id=run_id,
            repository_name=repo_name,
            model_used=settings.GEMINI_MODEL,
        )

        # 7. Update Analysis Run Status
        completion_time = _now_iso()
        with get_db_context() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = 'completed', completed_at = ?
                WHERE id = ?;
                """,
                (completion_time, run_id),
            )

        return report_meta

    except GeminiAuthError as auth_err:
        _mark_run_failed(run_id, str(auth_err))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(auth_err))
    except GeminiQuotaError as quota_err:
        _mark_run_failed(run_id, str(quota_err))
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(quota_err))
    except GeminiModelNotFoundError as model_err:
        _mark_run_failed(run_id, str(model_err))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(model_err))
    except GeminiTimeoutError as timeout_err:
        _mark_run_failed(run_id, str(timeout_err))
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(timeout_err))
    except GeminiUnavailableError as unavail_err:
        _mark_run_failed(run_id, str(unavail_err))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(unavail_err))
    except GeminiResponseError as resp_err:
        _mark_run_failed(run_id, str(resp_err))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(resp_err))
    except ValueError as val_err:
        _mark_run_failed(run_id, str(val_err))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(val_err))
    except GeminiError as gem_err:
        _mark_run_failed(run_id, str(gem_err))
        status_c = gem_err.status_code if (gem_err.status_code and 400 <= gem_err.status_code < 600) else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=status_c, detail=str(gem_err))
    except Exception as exc:
        logger.error("Analysis failed for repository %s: %s", repository_id, exc)
        _mark_run_failed(run_id, "Synthesis failed during AI processing or evidence verification.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI synthesis failed. Please ensure the model is accessible and try again.",
        )


def _mark_run_failed(run_id: str, error_message: str) -> None:
    """Helper to update analysis run record to failed status safely."""
    try:
        with get_db_context() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE id = ?;
                """,
                (_now_iso(), error_message, run_id),
            )
    except Exception as exc:
        logger.error("Could not update analysis run failure status: %s", exc)


@router.get(
    "/repositories/{repository_id}/reports",
    response_model=List[ReportSummaryResponse],
    summary="List Handover Reports for a Repository",
    description="Retrieve summaries of all synthesized handover reports for the specified repository.",
)
def get_repository_reports(repository_id: str) -> List[ReportSummaryResponse]:
    """List handover report summaries."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM repositories WHERE id = ?;", (repository_id,))
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repository_id}' not found.",
            )

    reports = list_reports_for_repository(repository_id)
    return [ReportSummaryResponse(**r) for r in reports]


@router.get(
    "/reports/{report_id}",
    response_model=ReportDetailResponse,
    summary="Retrieve Full Handover Report",
    description="Returns the complete handover report document including developer view, team lead view, and verification metadata.",
)
def get_report(report_id: str) -> ReportDetailResponse:
    """Retrieve complete report by ID."""
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Handover report '{report_id}' not found.",
        )
    return ReportDetailResponse(**report)


@router.post(
    "/reports/{report_id}/verify",
    summary="Re-run Deterministic Evidence Verification",
    description="Audits and recalculates citation integrity, SHA-256 hashes, and temporal consistency against current stored sources.",
)
def reverify_existing_report(report_id: str) -> Dict[str, Any]:
    """Re-verify existing report findings."""
    try:
        return reverify_report(report_id)
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(val_err))
    except Exception as exc:
        logger.error("Reverification failed for report %s: %s", report_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reverify report against stored evidence.",
        )


@router.get(
    "/reports/{report_id}/reviews",
    summary="Get Finding Review Decisions and Progress Summary",
    description="Retrieves the full human review history, latest finding decisions, and review progress summary.",
)
def get_report_reviews(report_id: str) -> Dict[str, Any]:
    """Retrieve review summary and audit trail for a report."""
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Handover report '{report_id}' not found.")
    summary, history = get_review_history_and_summary(report_id, report)
    return {
        "summary": summary,
        "history": history,
    }


@router.post(
    "/reports/{report_id}/reviews",
    status_code=status.HTTP_201_CREATED,
    response_model=ReviewDecisionRecord,
    summary="Record Finding Review Decision",
    description="Accept, reject, edit, or flag a finding for further investigation without overwriting original AI findings.",
)
def submit_finding_review(report_id: str, payload: CreateReviewDecisionRequest) -> ReviewDecisionRecord:
    """Submit a review decision for a finding."""
    try:
        return record_review_decision(report_id, payload)
    except ValueError as val_err:
        err_msg = str(val_err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as exc:
        logger.error("Failed to record review decision for report %s: %s", report_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist review decision.",
        )


@router.post(
    "/reports/{report_id}/finalize",
    summary="Finalize Handover Report Review",
    description="Finalize report review. Enforces that all findings have been reviewed before finalization.",
)
def finalize_report_review(report_id: str, payload: Optional[FinalizeReportRequest] = None) -> Dict[str, Any]:
    """Finalize report review lifecycle."""
    req = payload or FinalizeReportRequest()
    try:
        return finalize_report(report_id, reviewer_name=req.reviewer_name or "Lead Reviewer (Demo)", final_notes=req.final_notes or "")
    except ValueError as val_err:
        err_msg = str(val_err)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as exc:
        logger.error("Failed to finalize report %s: %s", report_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to finalize handover report.",
        )


@router.post(
    "/reports/test-fixture",
    status_code=status.HTTP_201_CREATED,
    summary="Create Disposable Test Handover Report Fixture",
    description="Creates or resets a disposable test handover report with known findings and source chunks for automated verification and review testing without mutating the production demonstration report.",
)
def create_test_report_fixture() -> Dict[str, Any]:
    """Create a fully-grounded disposable test report fixture for verification and acceptance testing."""
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, full_name FROM repositories LIMIT 1;")
        repo = cursor.fetchone()
        if not repo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No repository found in database.")
        repo_id = repo["id"]
        repo_name = repo["full_name"] or repo["name"]

        cursor.execute("SELECT id FROM source_chunks WHERE repository_id = ? LIMIT 1;", (repo_id,))
        chunk = cursor.fetchone()
        chunk_id = chunk["id"] if chunk else "chunk_3c16b3f9234b43db"

    findings = [
        Finding(
            id="TEST-FIND-001",
            category=FindingCategory.ARCHITECTURAL_DECISION,
            title="FastAPI Modular Architecture",
            description="Service uses modular routers and dependency injection for testability.",
            priority=PriorityLevel.MEDIUM,
            confidence=ConfidenceLevel.HIGH,
            evidence_source_ids=[chunk_id],
            evidence_explanation="Traceable to repository architecture setup.",
            verification_status=VerificationStatus.SOURCE_LINKED,
        ),
        Finding(
            id="TEST-FIND-002",
            category=FindingCategory.ACTIVE_WORK,
            title="Automated Test Runner & Verification",
            description="Continuous integration suite executing 99 backend integration tests.",
            priority=PriorityLevel.HIGH,
            confidence=ConfidenceLevel.HIGH,
            evidence_source_ids=[chunk_id],
            evidence_explanation="Traceable to test suite execution and configuration.",
            verification_status=VerificationStatus.SOURCE_LINKED,
        ),
    ]

    analysis = AnalysisResult(
        project_summary=f"Automated test handover fixture for {repo_name}.",
        architectural_decisions=[findings[0]],
        active_workstreams=[findings[1]],
        unfinished_work=[],
        blockers=[],
        technical_risks=[],
        fragile_modules=[],
        continuation_roadmap=[],
        uncertainties=[],
        evidence_references=[chunk_id],
        coverage_summary=CoverageSummary(
            total_available_chunks=1,
            analyzed_chunks=1,
            is_complete_coverage=True,
            coverage_percentage=100.0,
        ),
    )

    run_id = _generate_id("run_test")
    now = _now_iso()
    with get_db_context() as conn:
        conn.execute(
            """
            INSERT INTO analysis_runs (id, repository_id, status, started_at, completed_at)
            VALUES (?, ?, 'completed', ?, ?);
            """,
            (run_id, repo_id, now, now),
        )

    generator = ReportGenerator(repo_id)
    report_dict = generator.assemble_and_persist_report(
        analysis=analysis,
        analysis_run_id=run_id,
        repository_name=repo_name,
        model_used="Test Fixture (Automated)",
    )

    return {
        "report_id": report_dict["report_id"],
        "status": "created",
        "findings_count": 2,
        "title": report_dict["title"],
    }


@router.delete(
    "/reports/{report_id}",
    summary="Delete Handover Report (Test Disposable Only)",
    description="Deletes a disposable test report and associated review decisions. Cannot delete the production demo report.",
)
def delete_test_report(report_id: str) -> Dict[str, Any]:
    """Safely delete a disposable test report. Protected demo reports cannot be deleted."""
    if report_id == "rep_f34ab9bca2904063":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the protected demonstration report 'rep_f34ab9bca2904063'.",
        )
    with get_db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM handover_reports WHERE id = ?;", (report_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report '{report_id}' not found.")
        conn.execute("DELETE FROM review_decisions WHERE report_id = ?;", (report_id,))
        conn.execute("DELETE FROM handover_reports WHERE id = ?;", (report_id,))
    return {"report_id": report_id, "deleted": True}
