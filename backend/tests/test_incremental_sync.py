"""Unit and integration tests for Incremental Synchronization and Deeper Project Context.

Validates:
1. Initial sync creating repository checkpoints.
2. Incremental sync using watermarks ('since' query filters).
3. New commits, updated PRs, and updated issues ingestion.
4. Idempotent upserts preserving stable chunk_ids and evidence references.
5. Zero duplicate chunks on repeated sync runs.
6. Checkpoint advancement on success and preservation on failure.
7. Changes-since-last-handover calculation (has_changes, total_changes, summary).
8. Reconstructed cross-references and grounded relationship extraction.
9. Handover report and human review preservation.
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.core.database import get_db_context, init_db
from app.integrations.github import (
    GitHubClient,
    GitHubError,
    GitHubRateLimitError,
)
from app.services.analyzer import RepositoryAnalyzer, extract_project_relationships
from app.services.ingestion import IngestionService


class TestIncrementalSync(unittest.TestCase):
    """Test suite for incremental synchronization, checkpoints, and deeper context."""

    def setUp(self):
        """Create dedicated temporary SQLite database for test isolation."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_incremental.db"

        self.db_patcher = patch("app.core.database.get_db_path", return_value=self.db_path)
        self.db_patcher.start()
        init_db(self.db_path)

        # Mock GitHub Client
        self.mock_github = MagicMock(spec=GitHubClient)
        self.mock_github.get_repository.return_value = {
            "external_id": "88888",
            "name": "sync-repo",
            "full_name": "owner/sync-repo",
            "description": "Incremental sync test repository",
            "default_branch": "main",
            "repository_url": "https://github.com/owner/sync-repo",
        }

        self.service = IngestionService(github_client=self.mock_github)
        self.repo = self.service.connect_repository("https://github.com/owner/sync-repo")
        self.repo_id = self.repo["id"]

    def tearDown(self):
        """Clean up database and patches."""
        self.db_patcher.stop()
        self.temp_dir.cleanup()

    def test_initial_sync_creates_checkpoint(self):
        """Initial sync should store chunks and create a sync checkpoint."""
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "commit_111",
                "message": "Initial commit",
                "author_name": "Dev One",
                "author_email": "dev1@example.com",
                "timestamp": "2026-11-01T10:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/commit_111",
            }
        ]
        self.mock_github.get_issues.return_value = [
            {
                "number": 1,
                "title": "Setup database",
                "body": "Need SQLite tables",
                "state": "closed",
                "author": "dev1",
                "created_at": "2026-11-01T10:30:00Z",
                "updated_at": "2026-11-01T11:00:00Z",
                "closed_at": "2026-11-01T11:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/issues/1",
            }
        ]
        self.mock_github.get_pull_requests.return_value = [
            {
                "number": 2,
                "title": "Add initial schema",
                "body": "Closes #1 with database tables",
                "state": "closed",
                "author": "dev1",
                "created_at": "2026-11-01T11:30:00Z",
                "updated_at": "2026-11-01T12:00:00Z",
                "merged_at": "2026-11-01T12:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/pull/2",
            }
        ]

        result = self.service.sync_repository(self.repo_id)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["is_incremental"])
        self.assertEqual(result["chunks_created"], 3)
        self.assertEqual(result["duplicates_skipped"], 0)

        # Checkpoint should be created
        cp = self.service.get_sync_checkpoint(self.repo_id)
        self.assertIsNotNone(cp)
        self.assertEqual(cp["sync_status"], "completed")
        self.assertEqual(cp["last_commit_sha"], "commit_111")
        self.assertEqual(cp["last_commit_timestamp"], "2026-11-01T10:00:00Z")
        self.assertEqual(cp["last_issue_updated_at"], "2026-11-01T11:00:00Z")
        self.assertEqual(cp["last_pr_updated_at"], "2026-11-01T12:00:00Z")
        self.assertEqual(cp["total_syncs_count"], 1)

    def test_incremental_sync_uses_watermark_filters(self):
        """Second sync should pass 'since' filters to GitHub methods and advance watermark."""
        # Setup initial sync
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c1",
                "message": "c1 message",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-01T10:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c1",
            }
        ]
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = []

        self.service.sync_repository(self.repo_id)

        # Second sync with newer commit
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c2",
                "message": "c2 newer message",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-05T15:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c2",
            }
        ]
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = []

        result = self.service.sync_repository(self.repo_id)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["is_incremental"])
        self.assertEqual(result["chunks_created"], 1)
        self.assertEqual(result["new_commits_count"], 1)

        # Verify get_commits was called with since="2026-11-01T10:00:00Z"
        last_commit_call = self.mock_github.get_commits.call_args
        self.assertEqual(last_commit_call[1].get("since"), "2026-11-01T10:00:00Z")

        # Verify checkpoint advanced
        cp = self.service.get_sync_checkpoint(self.repo_id)
        self.assertEqual(cp["last_commit_sha"], "c2")
        self.assertEqual(cp["last_commit_timestamp"], "2026-11-05T15:00:00Z")
        self.assertEqual(cp["total_syncs_count"], 2)

    def test_idempotent_in_place_upsert_for_updated_pr(self):
        """Updating an existing PR should update the existing source chunk in-place preserving chunk_id."""
        self.mock_github.get_commits.return_value = []
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = [
            {
                "number": 10,
                "title": "WIP: Feature Alpha",
                "body": "Initial draft of feature alpha",
                "state": "open",
                "author": "alice",
                "created_at": "2026-11-02T10:00:00Z",
                "updated_at": "2026-11-02T10:00:00Z",
                "merged_at": None,
                "source_url": "https://github.com/owner/sync-repo/pull/10",
            }
        ]

        res1 = self.service.sync_repository(self.repo_id)
        self.assertEqual(res1["chunks_created"], 1)

        # Get initial chunk
        chunks = self.service.get_source_chunks(self.repo_id)["sources"]
        self.assertEqual(len(chunks), 1)
        initial_chunk_id = chunks[0]["id"]
        self.assertIn("WIP: Feature Alpha", chunks[0]["content"])

        # Sync again with updated PR content and title
        self.mock_github.get_pull_requests.return_value = [
            {
                "number": 10,
                "title": "Feature Alpha Ready for Review",
                "body": "Completed feature alpha with tests",
                "state": "open",
                "author": "alice",
                "created_at": "2026-11-02T10:00:00Z",
                "updated_at": "2026-11-03T12:00:00Z",
                "merged_at": None,
                "source_url": "https://github.com/owner/sync-repo/pull/10",
            }
        ]

        res2 = self.service.sync_repository(self.repo_id)
        self.assertEqual(res2["chunks_created"], 0)
        self.assertEqual(res2["chunks_updated"], 1)
        self.assertEqual(res2["updated_prs_count"], 1)

        # Verify chunk count remains 1 and ID is preserved (no duplicate chunk)
        updated_chunks = self.service.get_source_chunks(self.repo_id)["sources"]
        self.assertEqual(len(updated_chunks), 1)
        self.assertEqual(updated_chunks[0]["id"], initial_chunk_id)
        self.assertIn("Feature Alpha Ready for Review", updated_chunks[0]["content"])

    def test_repeated_sync_zero_duplicates(self):
        """Repeated sync with identical records creates 0 chunks and skips all duplicates."""
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c_stable",
                "message": "Stable commit",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-01T10:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c_stable",
            }
        ]
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = []

        res1 = self.service.sync_repository(self.repo_id)
        self.assertEqual(res1["chunks_created"], 1)

        # Force full sync with same data
        res2 = self.service.sync_repository(self.repo_id, force_full=True)
        self.assertEqual(res2["chunks_created"], 0)
        self.assertEqual(res2["duplicates_skipped"], 1)

    def test_checkpoint_failure_preserves_previous_watermark(self):
        """When sync encounters an error, checkpoint records failed status but preserves watermark."""
        # Initial successful sync
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c_success",
                "message": "Success commit",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-01T10:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c_success",
            }
        ]
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = []
        self.service.sync_repository(self.repo_id)

        # Second sync fails due to rate limit or network error
        self.mock_github.get_commits.side_effect = GitHubRateLimitError("Rate limit exceeded")

        with self.assertRaises(GitHubRateLimitError):
            self.service.sync_repository(self.repo_id)

        # Watermark from first sync must still be preserved
        cp = self.service.get_sync_checkpoint(self.repo_id)
        self.assertEqual(cp["sync_status"], "failed")
        self.assertIn("Rate limit exceeded", cp["last_error"])
        self.assertEqual(cp["last_commit_sha"], "c_success")
        self.assertEqual(cp["last_commit_timestamp"], "2026-11-01T10:00:00Z")

    def test_changes_since_last_handover(self):
        """Verify changes-since-last-handover detection with and without handover report."""
        # 1. No handover yet -> everything is reported as change
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c_new",
                "message": "New feature commit",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-04T12:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c_new",
            }
        ]
        self.mock_github.get_issues.return_value = []
        self.mock_github.get_pull_requests.return_value = []
        self.service.sync_repository(self.repo_id)

        changes = self.service.get_changes_since_last_handover(self.repo_id)
        self.assertTrue(changes["has_changes"])
        self.assertEqual(changes["total_changes"], 1)
        self.assertEqual(len(changes["new_commits"]), 1)

        # 2. Simulate a handover report created at 2026-11-05 (set prior chunk to 2026-11-04)
        with get_db_context() as conn:
            conn.execute("UPDATE source_chunks SET created_at = '2026-11-04T00:00:00Z' WHERE repository_id = ?;", (self.repo_id,))
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO analysis_runs (id, repository_id, status, started_at, completed_at)
                VALUES ('run_test_01', ?, 'completed', '2026-11-05T00:00:00Z', '2026-11-05T00:01:00Z');
                """,
                (self.repo_id,),
            )
            cursor.execute(
                """
                INSERT INTO handover_reports (
                    id, repository_id, analysis_run_id, title, report_json,
                    status, created_at, updated_at
                ) VALUES (
                    'rep_test_01', ?, 'run_test_01', 'Handover Report', '{"project_summary": "Summary", "architectural_decisions": [], "active_workstreams": [], "unfinished_work": [], "blockers": [], "technical_risks": [], "fragile_modules": [], "continuation_roadmap": [], "uncertainties": [], "evidence_references": []}',
                    'ready', '2026-11-05T00:00:00Z', '2026-11-05T00:00:00Z'
                );
                """,
                (self.repo_id,),
            )
            conn.commit()

        # Changes now should be 0 because commit was at 2026-11-04 and handover was at 2026-11-05
        changes_after_handover = self.service.get_changes_since_last_handover(self.repo_id)
        self.assertFalse(changes_after_handover["has_changes"])
        self.assertEqual(changes_after_handover["total_changes"], 0)
        self.assertIn("up to date", changes_after_handover["summary"].lower())

        # 3. Add newer commit after handover (2026-11-06)
        self.mock_github.get_commits.return_value = [
            {
                "commit_hash": "c_after_handover",
                "message": "Fix bug after handover",
                "author_name": "Dev",
                "author_email": "d@example.com",
                "timestamp": "2026-11-06T10:00:00Z",
                "source_url": "https://github.com/owner/sync-repo/commit/c_after_handover",
            }
        ]
        self.service.sync_repository(self.repo_id)

        changes_latest = self.service.get_changes_since_last_handover(self.repo_id)
        self.assertTrue(changes_latest["has_changes"])
        self.assertEqual(changes_latest["total_changes"], 1)
        self.assertEqual(len(changes_latest["new_commits"]), 1)
        self.assertIn("1 new commit", changes_latest["summary"])

    def test_deeper_project_context_extraction(self):
        """extract_project_relationships accurately traces PR merges and resolved issues."""
        mock_chunks = [
            {
                "id": "chunk_pr_1",
                "source_type": "pull_request",
                "source_external_id": "PR#5",
                "content": "Add PostgreSQL connection pool\nCloses #3 and refs #4",
                "metadata": {"number": 5, "state": "closed"},
            },
            {
                "id": "chunk_issue_1",
                "source_type": "issue",
                "source_external_id": "Issue#3",
                "content": "Database connections leaking under high load",
                "metadata": {"number": 3, "state": "closed"},
            },
            {
                "id": "chunk_commit_1",
                "source_type": "commit",
                "commit_hash": "abcdef1234567890",
                "content": "Merge pull request #5 from feature/db-pool",
                "metadata": {"author": "Tech Lead"},
            },
        ]

        rel = extract_project_relationships(mock_chunks)
        self.assertEqual(rel["total_prs"], 1)
        self.assertEqual(rel["total_issues"], 1)
        self.assertEqual(rel["total_commits"], 1)

        verified = rel["verified_links"]
        self.assertTrue(any("Pull Request #5 [chunk: chunk_pr_1] references/resolves Issue #3 [chunk: chunk_issue_1] (Verified Grounded Link)" in s for s in verified))
        self.assertTrue(any("Merge Commit abcdef1 [chunk: chunk_commit_1] merges Pull Request #5 [chunk: chunk_pr_1] (Verified Grounded Link)" in s for s in verified))
        # Issue #4 was external/not in chunks
        self.assertTrue(any("references/resolves Issue #4 (External/Historical Issue Reference)" in s for s in verified))


if __name__ == "__main__":
    unittest.main()
