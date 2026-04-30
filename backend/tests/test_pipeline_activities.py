"""Tests for W9a/W9b/W9c pipeline activities.

Uses --noconftest pattern: no conftest.py fixtures, all setup local.
All DB tables created from SQLModel metadata; no alembic migrations.
All external HTTP calls are mocked at the provider's _http_* method level.

Tests:
  test_start_pipeline_creates_correlation
  test_start_pipeline_duplicate_is_idempotent
  test_wait_pipeline_polls_until_complete
  test_wait_pipeline_heartbeats_progress
  test_cancel_pipeline_calls_provider
  test_artifact_download_stores_in_archon
  test_callback_retries_on_failure
  test_callback_dead_letters_after_max_retries
  test_github_adapter_normalizes_status
  test_generic_webhook_adapter
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")

# Register all SQLModel tables before creating schema.
import app.models  # noqa: F401  (side-effect: registers all SQLModel tables)

from app.services.activity_runtime_test_doubles import build_test_context

# ── In-memory SQLite engine ───────────────────────────────────────────────────

_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
)

_SESSION_FACTORY = sessionmaker(
    _ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)

TENANT_UUID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
RUN_UUID = UUID("11111111-2222-3333-4444-555555555555")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _create_tables():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def session():
    async with _SESSION_FACTORY() as s:
        yield s


# ── Helpers ───────────────────────────────────────────────────────────────────


def _context(
    *,
    node_config: dict[str, Any] | None = None,
    input_data: dict[str, Any] | None = None,
    session: Any = None,
    run_id: str | None = None,
    tenant_id: str | None = None,
) -> Any:
    ctx = build_test_context(
        node_config=node_config or {},
        input_data=input_data or {},
        run_id=run_id or str(uuid4()),
        tenant_id=tenant_id or str(TENANT_UUID),
    )
    # Inject the db_session via object mutation (dataclass is frozen — use
    # object.__setattr__ to inject without violating the frozen constraint).
    if session is not None:
        object.__setattr__(ctx, "db_session", session)
    return ctx


def _fake_provider_response(
    *,
    external_run_id: str = "run-123",
    status: str = "running",
    conclusion: str | None = None,
) -> dict[str, Any]:
    return {
        "external_run_id": external_run_id,
        "external_run_url": "https://example.com/runs/run-123",
        "status": status,
        "raw_status": status,
        "conclusion": conclusion,
        "error": None,
    }


# ── W9a: Provider adapter tests ───────────────────────────────────────────────


class TestGitHubAdapterNormalizesStatus:
    """test_github_adapter_normalizes_status"""

    def test_running_statuses(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        for raw in ("queued", "in_progress", "waiting", "requested", "pending"):
            assert p.normalize_status(raw) == "running", raw

    def test_completed_status(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        assert p.normalize_status("completed") == "completed"

    def test_unknown_status(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        assert p.normalize_status("some_future_status") == "unknown"

    @pytest.mark.asyncio
    async def test_get_pipeline_status_maps_conclusion(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        # Simulate completed + success conclusion.
        p._http_get = AsyncMock(
            return_value={
                "status_code": 200,
                "body": {
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/run/1",
                    "run_number": 42,
                },
            }
        )
        result = await p.get_pipeline_status(
            external_run_id="1",
            credentials={"token": "tok", "owner": "org", "repo": "repo"},
        )
        assert result["status"] == "completed"
        assert result["conclusion"] == "success"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_get_pipeline_status_failure_conclusion(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        p._http_get = AsyncMock(
            return_value={
                "status_code": 200,
                "body": {
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/run/2",
                    "run_number": 43,
                },
            }
        )
        result = await p.get_pipeline_status(
            external_run_id="2",
            credentials={"token": "tok", "owner": "org", "repo": "repo"},
        )
        assert result["status"] == "failed"
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_start_pipeline_returns_run_id(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        p._http_post = AsyncMock(return_value={"status_code": 204, "body": ""})
        p._http_get = AsyncMock(
            return_value={
                "status_code": 200,
                "body": {
                    "workflow_runs": [
                        {"id": 999, "html_url": "https://github.com/run/999"}
                    ]
                },
            }
        )
        result = await p.start_pipeline(
            config={
                "workflow_id": "ci.yml",
                "ref": "main",
            },
            credentials={"token": "tok", "owner": "myorg", "repo": "myrepo"},
        )
        assert result["external_run_id"] == "999"
        assert "myorg" in result.get("owner", "")

    @pytest.mark.asyncio
    async def test_cancel_pipeline_returns_true_on_202(self):
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        p = GitHubActionsProvider()
        p._http_post = AsyncMock(return_value={"status_code": 202, "body": ""})
        ok = await p.cancel_pipeline(
            external_run_id="42",
            credentials={"token": "tok", "owner": "org", "repo": "repo"},
        )
        assert ok is True


class TestGenericWebhookAdapter:
    """test_generic_webhook_adapter"""

    @pytest.mark.asyncio
    async def test_start_fires_post_and_returns_run_id(self):
        from app.services.pipeline_providers.generic_webhook import (
            GenericWebhookProvider,
        )

        p = GenericWebhookProvider()
        p._http_post = AsyncMock(
            return_value={
                "status_code": 202,
                "body": {"id": "wh-run-7", "status": "queued"},
            }
        )
        result = await p.start_pipeline(
            config={
                "trigger_url": "https://ci.example.com/webhooks/trigger",
                "run_id_field": "id",
            },
            credentials={},
        )
        assert result["external_run_id"] == "wh-run-7"

    @pytest.mark.asyncio
    async def test_get_status_polls_status_url(self):
        from app.services.pipeline_providers.generic_webhook import (
            GenericWebhookProvider,
        )

        p = GenericWebhookProvider()
        p._http_get = AsyncMock(
            return_value={
                "status_code": 200,
                "body": {"status": "success"},
            }
        )
        result = await p.get_pipeline_status(
            external_run_id="wh-run-7",
            credentials={},
            config={
                "status_url": "https://ci.example.com/runs/{run_id}",
                "completed_values": ["success"],
            },
        )
        assert result["status"] == "completed"

    def test_normalize_status_uses_config_lists(self):
        from app.services.pipeline_providers.generic_webhook import (
            GenericWebhookProvider,
        )

        p = GenericWebhookProvider()
        cfg = {
            "running_values": ["PENDING", "RUNNING"],
            "completed_values": ["OK"],
            "failed_values": ["ERROR"],
        }
        assert p.normalize_status("PENDING", config=cfg) == "running"
        assert p.normalize_status("OK", config=cfg) == "completed"
        assert p.normalize_status("ERROR", config=cfg) == "failed"

    @pytest.mark.asyncio
    async def test_cancel_returns_false_when_no_cancel_url(self):
        from app.services.pipeline_providers.generic_webhook import (
            GenericWebhookProvider,
        )

        p = GenericWebhookProvider()
        ok = await p.cancel_pipeline(
            external_run_id="wh-run-7",
            credentials={},
            config={},
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_start_raises_on_non_2xx(self):
        from app.services.pipeline_providers.generic_webhook import (
            GenericWebhookProvider,
        )

        p = GenericWebhookProvider()
        p._http_post = AsyncMock(
            return_value={"status_code": 500, "body": "Internal Server Error"}
        )
        with pytest.raises(RuntimeError, match="500"):
            await p.start_pipeline(
                config={"trigger_url": "https://ci.example.com/trigger"},
                credentials={},
            )


# ── W9b: Activity executor tests ──────────────────────────────────────────────


class TestStartPipelineCreatesCorrelation:
    """test_start_pipeline_creates_correlation"""

    @pytest.mark.asyncio
    async def test_creates_correlation_row(self, session: AsyncSession):
        from app.models.pipeline import PipelineCorrelation
        from app.services.node_executors.pipeline_start import execute_pipeline_start
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )
        from sqlmodel import select

        # Mock the provider.
        mock_provider = GitHubActionsProvider()
        mock_provider.start_pipeline = AsyncMock(
            return_value={
                "external_run_id": "run-abc",
                "external_run_url": "https://github.com/run/abc",
                "owner": "org",
                "repo": "repo",
                "workflow_id": "ci.yml",
                "ref": "main",
            }
        )

        run_id = str(uuid4())
        ctx = _context(
            node_config={
                "provider": "github_actions",
                "pipeline_config": {"workflow_id": "ci.yml", "ref": "main"},
                "credential_refs": {"token": "env://GH_TOKEN"},
            },
            session=session,
            run_id=run_id,
            tenant_id=str(TENANT_UUID),
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ), patch.dict(os.environ, {"GH_TOKEN": "fake-token"}):
            result = await execute_pipeline_start(ctx)

        assert result.status == "completed"
        assert result.output_data["external_run_id"] == "run-abc"
        assert result.output_data["provider"] == "github_actions"

        # Verify the PipelineCorrelation row was written.
        stmt = select(PipelineCorrelation).where(
            PipelineCorrelation.external_run_id == "run-abc"
        )
        corr_result = await session.exec(stmt)
        corr = corr_result.first()
        assert corr is not None
        assert corr.provider in ("github_actions", "generic_webhook")


class TestStartPipelineDuplicateIsIdempotent:
    """test_start_pipeline_duplicate_is_idempotent"""

    @pytest.mark.asyncio
    async def test_duplicate_returns_existing_correlation(self, session: AsyncSession):
        from app.services.node_executors.pipeline_start import execute_pipeline_start
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()
        mock_provider.start_pipeline = AsyncMock(
            return_value={
                "external_run_id": "run-idem-1",
                "external_run_url": None,
                "owner": "org",
                "repo": "repo",
            }
        )

        shared_run_id = str(uuid4())
        node_config = {
            "provider": "github_actions",
            "pipeline_config": {"workflow_id": "deploy.yml", "ref": "main"},
            "credential_refs": {},
            "idempotent": True,
        }

        ctx1 = _context(node_config=node_config, session=session, run_id=shared_run_id)
        ctx2 = _context(node_config=node_config, session=session, run_id=shared_run_id)

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result1 = await execute_pipeline_start(ctx1)
            result2 = await execute_pipeline_start(ctx2)

        assert result1.status == "completed"
        assert result2.status == "completed"
        # Second call must be an idempotency hit — provider was not called again.
        assert mock_provider.start_pipeline.call_count == 1
        assert result2.output_data.get("idempotent_hit") is True


class TestWaitPipelinePollsUntilComplete:
    """test_wait_pipeline_polls_until_complete"""

    @pytest.mark.asyncio
    async def test_polls_until_completed(self):
        from app.services.node_executors.pipeline_wait import execute_pipeline_wait
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        # First two polls return "running", third returns "completed".
        mock_provider = GitHubActionsProvider()
        mock_provider.get_pipeline_status = AsyncMock(
            side_effect=[
                {"status": "running", "raw_status": "in_progress", "conclusion": None, "error": None, "run_url": None},
                {"status": "running", "raw_status": "in_progress", "conclusion": None, "error": None, "run_url": None},
                {"status": "completed", "raw_status": "completed", "conclusion": "success", "error": None, "run_url": "https://gh.com/run/1"},
            ]
        )

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-poll-1",
                "credential_refs": {},
                "poll_interval_seconds": 0,  # no sleep in tests
                "max_polls": 10,
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_wait(ctx)

        assert result.status == "completed"
        assert result.output_data["status"] == "completed"
        assert result.output_data["polls"] == 3
        assert mock_provider.get_pipeline_status.call_count == 3

    @pytest.mark.asyncio
    async def test_fails_on_pipeline_failure(self):
        from app.services.node_executors.pipeline_wait import execute_pipeline_wait
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()
        mock_provider.get_pipeline_status = AsyncMock(
            return_value={
                "status": "failed",
                "raw_status": "completed",
                "conclusion": "failure",
                "error": {"message": "Build failed", "code": "failure", "details": {}},
                "run_url": None,
            }
        )

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-fail-1",
                "credential_refs": {},
                "poll_interval_seconds": 0,
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_wait(ctx)

        assert result.status == "failed"
        assert result.output_data["status"] == "failed"

    @pytest.mark.asyncio
    async def test_timeout_after_max_polls(self):
        from app.services.node_executors.pipeline_wait import execute_pipeline_wait
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()
        # Always returns running.
        mock_provider.get_pipeline_status = AsyncMock(
            return_value={
                "status": "running",
                "raw_status": "in_progress",
                "conclusion": None,
                "error": None,
                "run_url": None,
            }
        )

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-timeout",
                "credential_refs": {},
                "poll_interval_seconds": 0,
                "max_polls": 3,
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_wait(ctx)

        assert result.status == "failed"
        assert result.error_code == "PipelineWaitTimeout"


class TestWaitPipelineHeartbeatsProgress:
    """test_wait_pipeline_heartbeats_progress"""

    @pytest.mark.asyncio
    async def test_heartbeat_called_on_each_poll(self):
        from app.services.node_executors.pipeline_wait import execute_pipeline_wait
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        heartbeat_calls: list[dict] = []

        async def _capture_heartbeat(details: dict) -> None:
            heartbeat_calls.append(details)

        mock_provider = GitHubActionsProvider()
        mock_provider.get_pipeline_status = AsyncMock(
            side_effect=[
                {"status": "running", "raw_status": "queued", "conclusion": None, "error": None, "run_url": None},
                {"status": "completed", "raw_status": "completed", "conclusion": "success", "error": None, "run_url": None},
            ]
        )

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-hb",
                "credential_refs": {},
                "poll_interval_seconds": 0,
            },
        )
        object.__setattr__(ctx, "heartbeat", _capture_heartbeat)

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            await execute_pipeline_wait(ctx)

        assert len(heartbeat_calls) == 2
        assert heartbeat_calls[0]["current_status"] == "running"
        assert heartbeat_calls[1]["current_status"] == "completed"
        assert all("polls" in hb for hb in heartbeat_calls)


class TestCancelPipelineCallsProvider:
    """test_cancel_pipeline_calls_provider"""

    @pytest.mark.asyncio
    async def test_cancel_invokes_provider_cancel(self):
        from app.services.node_executors.pipeline_cancel import (
            execute_pipeline_cancel,
        )
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()
        mock_provider.cancel_pipeline = AsyncMock(return_value=True)

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-cancel-1",
                "credential_refs": {},
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_cancel(ctx)

        assert result.status == "completed"
        assert result.output_data["accepted"] is True
        mock_provider.cancel_pipeline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_accepted_false_still_returns_completed(self):
        from app.services.node_executors.pipeline_cancel import (
            execute_pipeline_cancel,
        )
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()
        mock_provider.cancel_pipeline = AsyncMock(return_value=False)

        ctx = _context(
            node_config={
                "provider": "github_actions",
                "external_run_id": "run-cancel-2",
                "credential_refs": {},
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_cancel(ctx)

        assert result.status == "completed"
        assert result.output_data["accepted"] is False

    @pytest.mark.asyncio
    async def test_cancel_requires_external_run_id(self):
        from app.services.node_executors.pipeline_cancel import (
            execute_pipeline_cancel,
        )
        from app.services.pipeline_providers.github_actions import (
            GitHubActionsProvider,
        )

        mock_provider = GitHubActionsProvider()

        ctx = _context(
            node_config={
                "provider": "github_actions",
                # external_run_id deliberately omitted
                "credential_refs": {},
            },
        )

        with patch(
            "app.services.pipeline_providers.get_provider",
            return_value=mock_provider,
        ):
            result = await execute_pipeline_cancel(ctx)

        assert result.status == "failed"
        assert result.error_code == "ValueError"


# ── W9c: Artifact download / callback tests ───────────────────────────────────


class TestArtifactDownloadStoresInArchon:
    """test_artifact_download_stores_in_archon"""

    @pytest.mark.asyncio
    async def test_downloads_and_stores_artifact(self):
        from app.services.node_executors.pipeline_artifact import (
            execute_pipeline_artifact_download,
        )

        stored_artifacts: list[tuple] = []

        async def _mock_write_artifact(
            name: str, payload: bytes | str | dict, metadata: dict
        ) -> str:
            stored_artifacts.append((name, payload, metadata))
            return f"artifact://test/{name}/fake-uuid"

        ctx = _context(
            node_config={
                "download_url": "https://example.com/artifacts/output.txt",
                "artifact_name": "pipeline_output",
                "credential_refs": {},
            },
        )
        object.__setattr__(ctx, "write_artifact", _mock_write_artifact)

        fake_content = b"artifact content bytes"

        with patch(
            "app.services.node_executors.pipeline_artifact._http_get_bytes",
            new=AsyncMock(
                return_value={"status_code": 200, "body": fake_content}
            ),
        ):
            result = await execute_pipeline_artifact_download(ctx)

        assert result.status == "completed"
        assert result.output_data["artifact_name"] == "pipeline_output"
        assert result.output_data["bytes_downloaded"] == len(fake_content)
        assert len(stored_artifacts) == 1
        _name, _payload, _meta = stored_artifacts[0]
        assert _name == "pipeline_output"
        assert _payload == fake_content

    @pytest.mark.asyncio
    async def test_download_failure_returns_failed(self):
        from app.services.node_executors.pipeline_artifact import (
            execute_pipeline_artifact_download,
        )

        ctx = _context(
            node_config={
                "download_url": "https://example.com/artifacts/missing.txt",
                "credential_refs": {},
            },
        )

        with patch(
            "app.services.node_executors.pipeline_artifact._http_get_bytes",
            new=AsyncMock(
                return_value={"status_code": 404, "body": b"Not Found"}
            ),
        ):
            result = await execute_pipeline_artifact_download(ctx)

        assert result.status == "failed"
        assert "404" in (result.error_code or "")

    @pytest.mark.asyncio
    async def test_download_requires_url(self):
        from app.services.node_executors.pipeline_artifact import (
            execute_pipeline_artifact_download,
        )

        ctx = _context(node_config={"credential_refs": {}})
        result = await execute_pipeline_artifact_download(ctx)
        assert result.status == "failed"
        assert result.error_code == "ValueError"


# ── W9c: Callback service tests ───────────────────────────────────────────────


class TestCallbackRetriesOnFailure:
    """test_callback_retries_on_failure"""

    @pytest.mark.asyncio
    async def test_retries_up_to_max_attempts(self, session: AsyncSession):
        from app.models.pipeline import PipelineCorrelation
        from app.services.pipeline_callback import send_status_callback

        # Insert a correlation row with a callback_url.
        corr_id = uuid4()
        run_id = uuid4()
        corr = PipelineCorrelation(
            id=corr_id,
            tenant_id=TENANT_UUID,
            workflow_run_id=run_id,
            provider="generic_webhook",
            external_event_id=f"test:{corr_id}",
            external_run_id="run-cb-1",
            idempotency_key=f"idem:{corr_id}",
            callback_url="https://callback.example.com/status",
        )
        session.add(corr)
        await session.commit()

        attempt_count = 0

        async def _failing_post(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            # Fail first two, succeed on third.
            if attempt_count < 3:
                return False, 503, "Service Unavailable"
            return True, 200, "OK"

        with patch(
            "app.services.pipeline_callback._post_callback",
            new=_failing_post,
        ), patch(
            "app.services.pipeline_callback._audit_callback_attempt",
            new=AsyncMock(),
        ):
            success = await send_status_callback(
                session,
                correlation_id=corr_id,
                status="completed",
            )

        assert success is True
        assert attempt_count == 3


class TestCallbackDeadLettersAfterMaxRetries:
    """test_callback_dead_letters_after_max_retries"""

    @pytest.mark.asyncio
    async def test_dead_letters_after_all_failures(self, session: AsyncSession):
        from app.models.pipeline import PipelineCorrelation
        from app.services.pipeline_callback import send_status_callback

        corr_id = uuid4()
        run_id = uuid4()
        corr = PipelineCorrelation(
            id=corr_id,
            tenant_id=TENANT_UUID,
            workflow_run_id=run_id,
            provider="generic_webhook",
            external_event_id=f"test-dl:{corr_id}",
            external_run_id="run-dl-1",
            idempotency_key=f"idem-dl:{corr_id}",
            callback_url="https://dead-callback.example.com/status",
        )
        session.add(corr)
        await session.commit()

        dead_letter_events: list[dict] = []

        async def _always_fail(*args, **kwargs):
            return False, 500, "Internal Server Error"

        async def _capture_dead_letter(**kwargs):
            dead_letter_events.append(kwargs)

        with patch(
            "app.services.pipeline_callback._post_callback",
            new=_always_fail,
        ), patch(
            "app.services.pipeline_callback._audit_callback_attempt",
            new=AsyncMock(),
        ), patch(
            "app.services.pipeline_callback._emit_dead_letter_event",
            new=AsyncMock(side_effect=_capture_dead_letter),
        ):
            success = await send_status_callback(
                session,
                correlation_id=corr_id,
                status="failed",
                details={"reason": "test"},
            )

        assert success is False
        # Dead-letter event must be emitted exactly once.
        assert len(dead_letter_events) == 1
        assert dead_letter_events[0]["correlation_id"] == str(corr_id)
        assert dead_letter_events[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_no_callback_url_returns_true(self, session: AsyncSession):
        from app.models.pipeline import PipelineCorrelation
        from app.services.pipeline_callback import send_status_callback

        corr_id = uuid4()
        run_id = uuid4()
        corr = PipelineCorrelation(
            id=corr_id,
            tenant_id=TENANT_UUID,
            workflow_run_id=run_id,
            provider="generic_webhook",
            external_event_id=f"test-no-cb:{corr_id}",
            external_run_id="run-no-cb",
            idempotency_key=f"idem-no-cb:{corr_id}",
            callback_url=None,  # no callback configured
        )
        session.add(corr)
        await session.commit()

        success = await send_status_callback(
            session,
            correlation_id=corr_id,
            status="completed",
        )
        assert success is True  # Not an error — callback not configured.
