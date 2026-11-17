"""Repository History Ingestion and Normalization Service.

Coordinates:
- GitHub REST API data retrieval (commits, issues, PRs)
- Local Git inspection fallback where applicable
- Deterministic secret sanitization prior to persistence
- SHA-256 content hashing and idempotent duplicate detection
- Relational SQLite storage into repositories, analysis_runs, and source_chunks
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.config import get_settings
from app.core.database import get_db_context
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    parse_and_validate_github_url,
)
from app.utils.sanitizer import sanitize_text

logger = logging.getLogger("relaypoint.ingestion")


def _generate_id(prefix: str) -> str:
    """Generate a unique prefixed identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _compute_hash(text: str) -> str:
    """Compute deterministic SHA-256 hash of content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IngestionService:
    """Coordinates repository history ingestion, sanitization, and persistence."""

    def __init__(self, github_client: Optional[GitHubClient] = None):
        self.github_client = github_client or GitHubClient()
        self.settings = get_settings()

    def connect_repository(self, repository_url: str, custom_name: Optional[str] = None) -> Dict[str, Any]:
        """Validate and register a repository in the database.
        
        Args:
            repository_url: GitHub repository URL.
            custom_name: Optional display name override.
            
        Returns:
            Dictionary representing the stored repository record.
        """
        owner, repo_name = parse_and_validate_github_url(repository_url)
        full_name = f"{owner}/{repo_name}"

        # Check if already registered
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM repositories WHERE full_name = ?;", (full_name,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

        # Retrieve remote metadata from GitHub
        remote_meta = self.github_client.get_repository(owner, repo_name)

        repo_id = _generate_id("repo")
        now = _now_iso()
        name = custom_name.strip() if custom_name and custom_name.strip() else remote_meta["name"]

        with get_db_context() as conn:
            conn.execute(
                """
                INSERT INTO repositories (
                    id, provider, external_repository_id, name, full_name,
                    description, default_branch, repository_url, created_at, updated_at
                ) VALUES (?, 'github', ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    repo_id,
                    remote_meta.get("external_id"),
                    name,
                    full_name,
                    remote_meta.get("description", ""),
                    remote_meta.get("default_branch", "main"),
                    remote_meta.get("repository_url", repository_url),
                    now,
                    now,
                ),
            )

        return self.get_repository_by_id(repo_id)

    def get_repository_by_id(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve repository record by primary key."""
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM repositories WHERE id = ?;", (repo_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_source_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific source chunk by primary key."""
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM source_chunks WHERE id = ?;", (chunk_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata_json", "{}"))
            except Exception:
                item["metadata"] = {}
            return item

    def list_repositories(self) -> List[Dict[str, Any]]:
        """List all connected repositories ordered by most recent."""
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM repositories ORDER BY created_at DESC;")
            return [dict(row) for row in cursor.fetchall()]

    def get_sync_checkpoint(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the latest synchronization checkpoint for a repository."""
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT repository_id, last_sync_at, last_commit_sha, last_commit_timestamp,
                       last_pr_updated_at, last_issue_updated_at, sync_status, last_error,
                       total_syncs_count, new_commits_count, updated_prs_count, updated_issues_count,
                       created_at, updated_at
                FROM repository_sync_checkpoints
                WHERE repository_id = ?;
                """,
                (repo_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def _save_sync_checkpoint(
        self,
        repo_id: str,
        last_sync_at: str,
        last_commit_sha: Optional[str],
        last_commit_timestamp: Optional[str],
        last_pr_updated_at: Optional[str],
        last_issue_updated_at: Optional[str],
        sync_status: str = "completed",
        last_error: Optional[str] = None,
        new_commits_count: int = 0,
        updated_prs_count: int = 0,
        updated_issues_count: int = 0,
    ) -> None:
        """Persist or advance the repository synchronization checkpoint."""
        now = _now_iso()
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT total_syncs_count, created_at FROM repository_sync_checkpoints WHERE repository_id = ?;", (repo_id,))
            existing = cursor.fetchone()
            if existing:
                total_syncs = existing["total_syncs_count"] + (1 if sync_status == "completed" else 0)
                conn.execute(
                    """
                    UPDATE repository_sync_checkpoints
                    SET last_sync_at = ?, last_commit_sha = ?, last_commit_timestamp = ?,
                        last_pr_updated_at = ?, last_issue_updated_at = ?, sync_status = ?,
                        last_error = ?, total_syncs_count = ?, new_commits_count = ?,
                        updated_prs_count = ?, updated_issues_count = ?, updated_at = ?
                    WHERE repository_id = ?;
                    """,
                    (
                        last_sync_at,
                        last_commit_sha,
                        last_commit_timestamp,
                        last_pr_updated_at,
                        last_issue_updated_at,
                        sync_status,
                        last_error,
                        total_syncs,
                        new_commits_count,
                        updated_prs_count,
                        updated_issues_count,
                        now,
                        repo_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO repository_sync_checkpoints (
                        repository_id, last_sync_at, last_commit_sha, last_commit_timestamp,
                        last_pr_updated_at, last_issue_updated_at, sync_status, last_error,
                        total_syncs_count, new_commits_count, updated_prs_count, updated_issues_count,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?);
                    """,
                    (
                        repo_id,
                        last_sync_at,
                        last_commit_sha,
                        last_commit_timestamp,
                        last_pr_updated_at,
                        last_issue_updated_at,
                        sync_status,
                        last_error,
                        new_commits_count,
                        updated_prs_count,
                        updated_issues_count,
                        now,
                        now,
                    ),
                )

    def sync_repository(self, repo_id: str, force_full: bool = False) -> Dict[str, Any]:
        """Alias for incremental repository synchronization."""
        return self.ingest_repository(repo_id=repo_id, force_full=force_full)

    def ingest_repository(self, repo_id: str, force_full: bool = False) -> Dict[str, Any]:
        """Execute history ingestion or incremental synchronization for a registered repository.
        
        If a checkpoint exists and force_full is False, performs incremental synchronization
        using GitHub 'since' and 'updated' filters. Otherwise performs full initial ingestion.
        """
        repo = self.get_repository_by_id(repo_id)
        if not repo:
            raise ValueError(f"Repository with ID '{repo_id}' not found.")

        owner, repo_name = parse_and_validate_github_url(repo["repository_url"])

        # Check existing checkpoint
        checkpoint = None if force_full else self.get_sync_checkpoint(repo_id)
        is_incremental = bool(checkpoint and checkpoint.get("sync_status") == "completed")

        since_commits = checkpoint.get("last_commit_timestamp") if is_incremental else None
        since_issues = checkpoint.get("last_issue_updated_at") if is_incremental else None
        since_prs = checkpoint.get("last_pr_updated_at") if is_incremental else None

        # 1. Initialize analysis run record
        run_id = _generate_id("run")
        start_time = _now_iso()

        with get_db_context() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (id, repository_id, status, started_at)
                VALUES (?, ?, 'running', ?);
                """,
                (run_id, repo_id, start_time),
            )
            if checkpoint:
                conn.execute(
                    "UPDATE repository_sync_checkpoints SET sync_status = 'in_progress', updated_at = ? WHERE repository_id = ?;",
                    (start_time, repo_id),
                )

        chunks_created = 0
        chunks_updated = 0
        duplicates_skipped = 0

        newest_commit_sha = checkpoint.get("last_commit_sha") if checkpoint else None
        newest_commit_ts = since_commits
        newest_issue_ts = since_issues
        newest_pr_ts = since_prs

        new_commits_count = 0
        new_issues_count = 0
        new_prs_count = 0

        try:
            # 2. Ingest Commits (using since if incremental)
            commits = self.github_client.get_commits(
                owner,
                repo_name,
                limit=self.settings.MAX_COMMITS,
                branch=repo.get("default_branch"),
                since=since_commits,
            )
            for c in commits:
                created, updated, skipped = self._persist_source_chunk(
                    repo_id=repo_id,
                    source_type="commit",
                    source_external_id=c.get("commit_hash"),
                    commit_hash=c.get("commit_hash"),
                    raw_content=c.get("message", ""),
                    source_url=c.get("source_url"),
                    metadata={
                        "author_name": c.get("author_name"),
                        "author_email": c.get("author_email"),
                        "timestamp": c.get("timestamp"),
                    },
                )
                chunks_created += created
                chunks_updated += updated
                duplicates_skipped += skipped
                if created > 0:
                    new_commits_count += 1
                c_ts = c.get("timestamp")
                if c_ts and (not newest_commit_ts or c_ts > newest_commit_ts):
                    newest_commit_ts = c_ts
                    newest_commit_sha = c.get("commit_hash")

            # 3. Ingest Issues (using since if incremental)
            issues = self.github_client.get_issues(
                owner,
                repo_name,
                state="all",
                limit=self.settings.MAX_ISSUES,
                since=since_issues,
            )
            for iss in issues:
                issue_content = f"{iss.get('title', '')}\n\n{iss.get('body', '')}".strip()
                created, updated, skipped = self._persist_source_chunk(
                    repo_id=repo_id,
                    source_type="issue",
                    source_external_id=str(iss.get("number")),
                    commit_hash=None,
                    raw_content=issue_content,
                    source_url=iss.get("source_url"),
                    metadata={
                        "number": iss.get("number"),
                        "title": iss.get("title"),
                        "state": iss.get("state"),
                        "author": iss.get("author"),
                        "created_at": iss.get("created_at"),
                        "updated_at": iss.get("updated_at"),
                        "closed_at": iss.get("closed_at"),
                        "labels": iss.get("labels", []),
                    },
                )
                chunks_created += created
                chunks_updated += updated
                duplicates_skipped += skipped
                if created > 0 or updated > 0:
                    new_issues_count += 1
                iss_upd = iss.get("updated_at")
                if iss_upd and (not newest_issue_ts or iss_upd > newest_issue_ts):
                    newest_issue_ts = iss_upd

            # 4. Ingest Pull Requests (using since if incremental)
            prs = self.github_client.get_pull_requests(
                owner,
                repo_name,
                state="all",
                limit=self.settings.MAX_PULL_REQUESTS,
                since=since_prs,
            )
            for pr in prs:
                pr_content = f"{pr.get('title', '')}\n\n{pr.get('body', '')}".strip()
                created, updated, skipped = self._persist_source_chunk(
                    repo_id=repo_id,
                    source_type="pull_request",
                    source_external_id=str(pr.get("number")),
                    commit_hash=None,
                    raw_content=pr_content,
                    source_url=pr.get("source_url"),
                    metadata={
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "state": pr.get("state"),
                        "author": pr.get("author"),
                        "created_at": pr.get("created_at"),
                        "updated_at": pr.get("updated_at"),
                        "closed_at": pr.get("closed_at"),
                        "merged_at": pr.get("merged_at"),
                        "head_branch": pr.get("head_branch"),
                        "base_branch": pr.get("base_branch"),
                    },
                )
                chunks_created += created
                chunks_updated += updated
                duplicates_skipped += skipped
                if created > 0 or updated > 0:
                    new_prs_count += 1
                pr_upd = pr.get("updated_at")
                if pr_upd and (not newest_pr_ts or pr_upd > newest_pr_ts):
                    newest_pr_ts = pr_upd

            # 5. Mark Run Complete
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
                conn.execute(
                    "UPDATE repositories SET updated_at = ? WHERE id = ?;",
                    (completion_time, repo_id),
                )

            # Advance checkpoint only after complete success
            self._save_sync_checkpoint(
                repo_id=repo_id,
                last_sync_at=completion_time,
                last_commit_sha=newest_commit_sha,
                last_commit_timestamp=newest_commit_ts,
                last_pr_updated_at=newest_pr_ts,
                last_issue_updated_at=newest_issue_ts,
                sync_status="completed",
                last_error=None,
                new_commits_count=new_commits_count,
                updated_prs_count=new_prs_count,
                updated_issues_count=new_issues_count,
            )

            return {
                "run_id": run_id,
                "repository_id": repo_id,
                "status": "completed",
                "chunks_created": chunks_created,
                "chunks_updated": chunks_updated,
                "duplicates_skipped": duplicates_skipped,
                "is_incremental": is_incremental,
                "new_commits_count": new_commits_count,
                "updated_prs_count": new_prs_count,
                "updated_issues_count": new_issues_count,
                "started_at": start_time,
                "completed_at": completion_time,
            }

        except Exception as exc:
            logger.error("Ingestion run %s failed: %s", run_id, exc)
            err_msg = str(exc)
            with get_db_context() as conn:
                conn.execute(
                    """
                    UPDATE analysis_runs
                    SET status = 'failed', completed_at = ?, error_message = ?
                    WHERE id = ?;
                    """,
                    (_now_iso(), run_id, err_msg),
                )
            if checkpoint:
                self._save_sync_checkpoint(
                    repo_id=repo_id,
                    last_sync_at=checkpoint.get("last_sync_at") or _now_iso(),
                    last_commit_sha=checkpoint.get("last_commit_sha"),
                    last_commit_timestamp=checkpoint.get("last_commit_timestamp"),
                    last_pr_updated_at=checkpoint.get("last_pr_updated_at"),
                    last_issue_updated_at=checkpoint.get("last_issue_updated_at"),
                    sync_status="failed",
                    last_error=err_msg,
                    new_commits_count=0,
                    updated_prs_count=0,
                    updated_issues_count=0,
                )
            raise

    def _persist_source_chunk(
        self,
        repo_id: str,
        source_type: str,
        source_external_id: Optional[str],
        commit_hash: Optional[str],
        raw_content: str,
        source_url: Optional[str],
        metadata: Dict[str, Any],
    ) -> Tuple[int, int, int]:
        """Sanitize, hash, and persist a source chunk with idempotent upsert.
        
        Returns:
            (created_count, updated_count, skipped_count)
        """
        # Bounded character length
        bounded_raw = raw_content[: self.settings.MAX_CONTENT_LENGTH] if raw_content else ""

        # CRITICAL SECURITY RULE: Sanitize raw content before hashing and persistence
        sanitized_content = sanitize_text(bounded_raw)
        content_hash = _compute_hash(sanitized_content)

        now = _now_iso()
        metadata_str = json.dumps(metadata)

        with get_db_context() as conn:
            cursor = conn.cursor()

            # 1. Stable external identifier matching for PRs and issues (handles state/body updates in-place)
            if source_external_id and source_type in ("pull_request", "issue"):
                cursor.execute(
                    """
                    SELECT id, content_hash, metadata_json
                    FROM source_chunks
                    WHERE repository_id = ? AND source_type = ? AND source_external_id = ?;
                    """,
                    (repo_id, source_type, source_external_id),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing["content_hash"] == content_hash and existing["metadata_json"] == metadata_str:
                        return 0, 0, 1  # Unchanged, skip

                    # Safe in-place update: preserves chunk_id so evidence_references remain valid
                    conn.execute(
                        """
                        UPDATE source_chunks
                        SET content = ?, content_hash = ?, metadata_json = ?, source_url = ?, created_at = ?
                        WHERE id = ?;
                        """,
                        (sanitized_content, content_hash, metadata_str, source_url, now, existing["id"]),
                    )
                    return 0, 1, 0  # Updated in-place

            # 2. Immutable commits matching by commit_hash
            if commit_hash and source_type == "commit":
                cursor.execute(
                    "SELECT id FROM source_chunks WHERE repository_id = ? AND source_type = 'commit' AND commit_hash = ?;",
                    (repo_id, commit_hash),
                )
                if cursor.fetchone():
                    return 0, 0, 1  # Commit already stored

            # 3. Duplicate content hash check
            cursor.execute(
                "SELECT id FROM source_chunks WHERE repository_id = ? AND content_hash = ?;",
                (repo_id, content_hash),
            )
            if cursor.fetchone():
                return 0, 0, 1  # Exact duplicate content

            # 4. Insert new chunk
            chunk_id = _generate_id("chunk")
            conn.execute(
                """
                INSERT INTO source_chunks (
                    id, repository_id, source_type, source_external_id,
                    commit_hash, content, content_hash, source_url,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    chunk_id,
                    repo_id,
                    source_type,
                    source_external_id,
                    commit_hash,
                    sanitized_content,
                    content_hash,
                    source_url,
                    metadata_str,
                    now,
                ),
            )
        return 1, 0, 0

    def get_changes_since_last_handover(self, repo_id: str) -> Dict[str, Any]:
        """Compile a summary of new commits, PRs, and issues added or modified since the latest handover report."""
        repo = self.get_repository_by_id(repo_id)
        if not repo:
            raise ValueError(f"Repository with ID '{repo_id}' not found.")

        checkpoint = self.get_sync_checkpoint(repo_id)

        # 1. Find latest handover report
        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, title, status, created_at
                FROM handover_reports
                WHERE repository_id = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (repo_id,),
            )
            latest_report_row = cursor.fetchone()
            latest_report = dict(latest_report_row) if latest_report_row else None

        watermark = latest_report["created_at"] if latest_report else None

        # 2. Query chunks created or updated after watermark
        with get_db_context() as conn:
            cursor = conn.cursor()
            if watermark:
                cursor.execute(
                    """
                    SELECT id, source_type, source_external_id, commit_hash, content, source_url, metadata_json, created_at
                    FROM source_chunks
                    WHERE repository_id = ? AND created_at > ?
                    ORDER BY created_at DESC;
                    """,
                    (repo_id, watermark),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, source_type, source_external_id, commit_hash, content, source_url, metadata_json, created_at
                    FROM source_chunks
                    WHERE repository_id = ?
                    ORDER BY created_at DESC;
                    """,
                    (repo_id,),
                )
            rows = cursor.fetchall()

        new_commits = []
        updated_prs = []
        updated_issues = []

        for r in rows:
            stype = r["source_type"]
            try:
                meta = json.loads(r["metadata_json"] or "{}")
            except Exception:
                meta = {}

            item = {
                "chunk_id": r["id"],
                "source_type": stype,
                "external_id": r["source_external_id"],
                "source_url": r["source_url"],
                "created_at": r["created_at"],
            }

            if stype == "commit":
                item["commit_hash"] = r["commit_hash"]
                item["message"] = r["content"].splitlines()[0] if r["content"] else ""
                item["author_name"] = meta.get("author_name", "Unknown")
                item["timestamp"] = meta.get("timestamp") or r["created_at"]
                new_commits.append(item)
            elif stype == "pull_request":
                item["number"] = meta.get("number") or r["source_external_id"]
                item["title"] = meta.get("title") or (r["content"].splitlines()[0] if r["content"] else "")
                item["state"] = meta.get("state", "unknown")
                item["author"] = meta.get("author", "Unknown")
                item["updated_at"] = meta.get("updated_at") or r["created_at"]
                updated_prs.append(item)
            elif stype == "issue":
                item["number"] = meta.get("number") or r["source_external_id"]
                item["title"] = meta.get("title") or (r["content"].splitlines()[0] if r["content"] else "")
                item["state"] = meta.get("state", "unknown")
                item["author"] = meta.get("author", "Unknown")
                item["updated_at"] = meta.get("updated_at") or r["created_at"]
                updated_issues.append(item)

        total_changes = len(new_commits) + len(updated_prs) + len(updated_issues)
        has_changes = total_changes > 0

        if not latest_report:
            summary = f"Initial sync: {len(new_commits)} commits, {len(updated_prs)} PRs, {len(updated_issues)} issues available for handover."
        elif has_changes:
            parts = []
            if new_commits:
                parts.append(f"{len(new_commits)} new commit{'s' if len(new_commits) != 1 else ''}")
            if updated_prs:
                parts.append(f"{len(updated_prs)} updated PR{'s' if len(updated_prs) != 1 else ''}")
            if updated_issues:
                parts.append(f"{len(updated_issues)} updated issue{'s' if len(updated_issues) != 1 else ''}")
            summary = f"{', '.join(parts)} since last handover report."
        else:
            summary = "Repository is up to date — no new activity since last handover report."

        return {
            "repository_id": repo_id,
            "has_changes": has_changes,
            "total_changes": total_changes,
            "new_commits": new_commits,
            "updated_prs": updated_prs,
            "updated_issues": updated_issues,
            "summary": summary,
            "last_handover": latest_report,
            "checkpoint": checkpoint,
        }

    def get_source_chunks(
        self,
        repo_id: str,
        source_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Fetch paginated source chunks for a repository."""
        limit = min(max(1, limit), 100)
        offset = max(0, offset)

        query = "SELECT * FROM source_chunks WHERE repository_id = ?"
        params: List[Any] = [repo_id]

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with get_db_context() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

            # Total count
            count_query = "SELECT count(*) FROM source_chunks WHERE repository_id = ?"
            count_params: List[Any] = [repo_id]
            if source_type:
                count_query += " AND source_type = ?"
                count_params.append(source_type)
            cursor.execute(count_query, tuple(count_params))
            total_count = cursor.fetchone()[0]

            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata_json", "{}"))
                except Exception:
                    item["metadata"] = {}
                results.append(item)

            return {
                "repository_id": repo_id,
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "sources": results,
            }

    def get_activity_timeline(self, repo_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Assemble a chronological activity timeline of commits, issues, and PRs."""
        chunks_data = self.get_source_chunks(repo_id, limit=limit, offset=0)
        timeline = []

        for chunk in chunks_data["sources"]:
            meta = chunk.get("metadata", {})
            source_type = chunk.get("source_type")

            # Determine timestamp
            event_time = meta.get("timestamp") or meta.get("created_at") or chunk.get("created_at")

            # Title / description
            if source_type == "commit":
                title = chunk["content"].splitlines()[0] if chunk["content"] else "Commit"
                author = meta.get("author_name", "Unknown")
            elif source_type in ("issue", "pull_request"):
                title = meta.get("title") or chunk["content"].splitlines()[0] if chunk["content"] else source_type.title()
                author = meta.get("author", "Unknown")
            else:
                title = chunk["content"][:60] if chunk["content"] else "Activity"
                author = "System"

            timeline.append({
                "source_id": chunk["id"],
                "source_type": source_type,
                "identifier": chunk.get("source_external_id"),
                "title": title,
                "author": author,
                "timestamp": event_time,
                "source_url": chunk.get("source_url"),
            })

        # Sort descending by timestamp
        timeline.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
        return timeline
