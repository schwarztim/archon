"""Unit tests for A2AClient and A2APublisher service classes.

Every DB interaction is mocked via AsyncSession so no real database is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.models.a2a import A2AAgentCard, A2AMessage, A2ATask
from app.services.a2a import A2AClient, A2APublisher


# ── Helpers / Fixtures ──────────────────────────────────────────────

CARD_ID = UUID("aabbccdd-1122-3344-5566-778899aabbcc")
CARD_ID_2 = UUID("11223344-aabb-ccdd-eeff-001122334455")
TASK_ID = UUID("aabb0011-2233-4455-6677-8899aabbccdd")
AGENT_ID = UUID("00112233-4455-6677-8899-aabbccddeeff")
MSG_ID = UUID("ddeeff00-1122-3344-5566-778899001122")


def _make_card(
    *,
    card_id: UUID = CARD_ID,
    name: str = "test-agent",
    url: str = "https://agent.example.com",
    direction: str = "inbound",
    is_active: bool = True,
    capabilities: list[str] | None = None,
    agent_id: UUID | None = None,
) -> A2AAgentCard:
    """Factory for A2AAgentCard instances."""
    return A2AAgentCard(
        id=card_id,
        name=name,
        url=url,
        direction=direction,
        is_active=is_active,
        capabilities=capabilities or [],
        agent_id=agent_id,
    )


def _make_task(
    *,
    task_id: UUID = TASK_ID,
    agent_card_id: UUID = CARD_ID,
    direction: str = "outbound",
    status: str = "submitted",
    input_data: dict[str, Any] | None = None,
) -> A2ATask:
    """Factory for A2ATask instances."""
    return A2ATask(
        id=task_id,
        agent_card_id=agent_card_id,
        direction=direction,
        status=status,
        input_data=input_data or {"prompt": "hello"},
    )


def _make_message(
    *,
    msg_id: UUID = MSG_ID,
    task_id: UUID = TASK_ID,
    role: str = "user",
    content: str = "ping",
) -> A2AMessage:
    """Factory for A2AMessage instances."""
    return A2AMessage(
        id=msg_id,
        task_id=task_id,
        role=role,
        content=content,
    )


def _mock_session() -> AsyncMock:
    """Return a fully-mocked AsyncSession with common methods."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock()
    session.exec = AsyncMock()
    return session


def _mock_exec_result(rows: list[Any]) -> AsyncMock:
    """Create a mock result object returned by session.exec()."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ── A2AClient Tests ─────────────────────────────────────────────────


class TestA2AClientGetAgentCard:
    """Tests for A2AClient.get_agent_card."""

    @pytest.mark.asyncio
    async def test_get_agent_card_found(self) -> None:
        """Returns the card when session.get finds it."""
        session = _mock_session()
        card = _make_card()
        session.get.return_value = card

        result = await A2AClient.get_agent_card(session, CARD_ID)

        assert result is card
        session.get.assert_awaited_once_with(A2AAgentCard, CARD_ID)

    @pytest.mark.asyncio
    async def test_get_agent_card_not_found(self) -> None:
        """Returns None when the card does not exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await A2AClient.get_agent_card(session, CARD_ID)

        assert result is None


class TestA2AClientDiscoverAgents:
    """Tests for A2AClient.discover_agents."""

    @pytest.mark.asyncio
    async def test_discover_returns_list_and_total(self) -> None:
        """Returns a tuple of (list, total_count)."""
        session = _mock_session()
        card = _make_card()
        count_result = _mock_exec_result([card])
        page_result = _mock_exec_result([card])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        entries, total = await A2AClient.discover_agents(session)

        assert total == 1
        assert entries == [card]

    @pytest.mark.asyncio
    async def test_discover_filters_by_capability(self) -> None:
        """Capability filter removes non-matching rows in-memory."""
        session = _mock_session()
        card_a = _make_card(card_id=CARD_ID, capabilities=["streaming"])
        card_b = _make_card(card_id=CARD_ID_2, capabilities=["push_notifications"])
        count_result = _mock_exec_result([card_a, card_b])
        page_result = _mock_exec_result([card_a, card_b])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        entries, total = await A2AClient.discover_agents(
            session, capability="streaming"
        )

        assert total == 1
        assert entries == [card_a]

    @pytest.mark.asyncio
    async def test_discover_empty_result(self) -> None:
        """Returns empty list and 0 total when no cards match."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        entries, total = await A2AClient.discover_agents(session)

        assert total == 0
        assert entries == []

    @pytest.mark.asyncio
    async def test_discover_respects_pagination(self) -> None:
        """limit and offset are forwarded to the query."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        await A2AClient.discover_agents(session, limit=5, offset=10)

        # exec called twice (count + paginated)
        assert session.exec.await_count == 2


class TestA2AClientRegisterAgentCard:
    """Tests for A2AClient.register_agent_card."""

    @pytest.mark.asyncio
    async def test_register_sets_direction_and_discovery_time(self) -> None:
        """register_agent_card forces direction='inbound' and sets last_discovered_at."""
        session = _mock_session()
        card = _make_card(direction="outbound")

        result = await A2AClient.register_agent_card(session, card)

        assert card.direction == "inbound"
        assert card.last_discovered_at is not None
        session.add.assert_called_once_with(card)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(card)


class TestA2AClientSendMessage:
    """Tests for A2AClient.send_message."""

    @pytest.mark.asyncio
    async def test_send_message_creates_and_commits(self) -> None:
        """A message is created, added, committed and refreshed."""
        session = _mock_session()

        result = await A2AClient.send_message(
            session, task_id=TASK_ID, role="user", content="hello"
        )

        assert isinstance(result, A2AMessage)
        assert result.task_id == TASK_ID
        assert result.role == "user"
        assert result.content == "hello"
        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_with_parts_and_metadata(self) -> None:
        """Parts and extra_metadata are stored on the message."""
        session = _mock_session()
        parts = [{"type": "text", "text": "hi"}]
        meta = {"source": "test"}

        result = await A2AClient.send_message(
            session,
            task_id=TASK_ID,
            role="agent",
            content="reply",
            parts=parts,
            extra_metadata=meta,
        )

        assert result.parts == parts
        assert result.extra_metadata == meta

    @pytest.mark.asyncio
    async def test_send_message_defaults_empty_parts(self) -> None:
        """When parts=None, defaults to empty list."""
        session = _mock_session()

        result = await A2AClient.send_message(
            session, task_id=TASK_ID, role="user", content="x"
        )

        assert result.parts == []
        assert result.extra_metadata == {}


class TestA2AClientCreateTask:
    """Tests for A2AClient.create_task."""

    @pytest.mark.asyncio
    async def test_create_task_sets_defaults(self) -> None:
        """New task has outbound direction and submitted status."""
        session = _mock_session()

        result = await A2AClient.create_task(
            session,
            agent_card_id=CARD_ID,
            input_data={"prompt": "test"},
        )

        assert isinstance(result, A2ATask)
        assert result.direction == "outbound"
        assert result.status == "submitted"
        assert result.agent_card_id == CARD_ID
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_task_with_metadata(self) -> None:
        """Extra metadata is stored on the task."""
        session = _mock_session()
        meta = {"priority": "high"}

        result = await A2AClient.create_task(
            session,
            agent_card_id=CARD_ID,
            input_data={"prompt": "test"},
            extra_metadata=meta,
        )

        assert result.extra_metadata == meta


class TestA2AClientGetTask:
    """Tests for A2AClient.get_task."""

    @pytest.mark.asyncio
    async def test_get_task_found(self) -> None:
        session = _mock_session()
        task = _make_task()
        session.get.return_value = task

        result = await A2AClient.get_task(session, TASK_ID)

        assert result is task
        session.get.assert_awaited_once_with(A2ATask, TASK_ID)

    @pytest.mark.asyncio
    async def test_get_task_not_found(self) -> None:
        session = _mock_session()
        session.get.return_value = None

        result = await A2AClient.get_task(session, TASK_ID)

        assert result is None


class TestA2AClientUpdateTaskStatus:
    """Tests for A2AClient.update_task_status."""

    @pytest.mark.asyncio
    async def test_update_status_to_working(self) -> None:
        """Transition to 'working' sets started_at if not already set."""
        session = _mock_session()
        task = _make_task()
        assert task.started_at is None
        session.get.return_value = task

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="working"
        )

        assert result is not None
        assert result.status == "working"
        assert result.started_at is not None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self) -> None:
        """Transition to 'completed' sets completed_at."""
        session = _mock_session()
        task = _make_task(status="working")
        session.get.return_value = task

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="completed", output_data={"answer": "42"}
        )

        assert result is not None
        assert result.status == "completed"
        assert result.completed_at is not None
        assert result.output_data == {"answer": "42"}

    @pytest.mark.asyncio
    async def test_update_status_to_failed_with_error(self) -> None:
        """Transition to 'failed' stores error and sets completed_at."""
        session = _mock_session()
        task = _make_task(status="working")
        session.get.return_value = task

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="failed", error="timeout"
        )

        assert result is not None
        assert result.status == "failed"
        assert result.error == "timeout"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_canceled(self) -> None:
        """Transition to 'canceled' sets completed_at."""
        session = _mock_session()
        task = _make_task(status="working")
        session.get.return_value = task

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="canceled"
        )

        assert result is not None
        assert result.status == "canceled"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_status_not_found(self) -> None:
        """Returns None when task doesn't exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="working"
        )

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_working_does_not_overwrite_started_at(self) -> None:
        """If started_at is already set, don't overwrite it."""
        session = _mock_session()
        task = _make_task(status="submitted")
        original_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        task.started_at = original_time
        session.get.return_value = task

        await A2AClient.update_task_status(session, TASK_ID, status="working")

        assert task.started_at == original_time


class TestA2AClientListTasks:
    """Tests for A2AClient.list_tasks."""

    @pytest.mark.asyncio
    async def test_list_tasks_returns_tuple(self) -> None:
        session = _mock_session()
        task = _make_task()
        count_result = _mock_exec_result([task])
        page_result = _mock_exec_result([task])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        tasks, total = await A2AClient.list_tasks(session)

        assert total == 1
        assert tasks == [task]

    @pytest.mark.asyncio
    async def test_list_tasks_empty(self) -> None:
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        tasks, total = await A2AClient.list_tasks(session)

        assert total == 0
        assert tasks == []


class TestA2AClientListMessages:
    """Tests for A2AClient.list_messages."""

    @pytest.mark.asyncio
    async def test_list_messages_returns_tuple(self) -> None:
        session = _mock_session()
        msg = _make_message()
        count_result = _mock_exec_result([msg])
        page_result = _mock_exec_result([msg])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        messages, total = await A2AClient.list_messages(session, task_id=TASK_ID)

        assert total == 1
        assert messages == [msg]

    @pytest.mark.asyncio
    async def test_list_messages_empty(self) -> None:
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        messages, total = await A2AClient.list_messages(session, task_id=TASK_ID)

        assert total == 0
        assert messages == []


# ── A2APublisher Tests ──────────────────────────────────────────────


class TestA2APublisherPublishCard:
    """Tests for A2APublisher.publish_card."""

    @pytest.mark.asyncio
    async def test_publish_sets_outbound_and_active(self) -> None:
        """publish_card forces direction='outbound' and is_active=True."""
        session = _mock_session()
        card = _make_card(direction="inbound", is_active=False)

        result = await A2APublisher.publish_card(session, card)

        assert card.direction == "outbound"
        assert card.is_active is True
        session.add.assert_called_once_with(card)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(card)

    @pytest.mark.asyncio
    async def test_publish_returns_the_card(self) -> None:
        session = _mock_session()
        card = _make_card()

        result = await A2APublisher.publish_card(session, card)

        assert result is card


class TestA2APublisherUpdateCard:
    """Tests for A2APublisher.update_card."""

    @pytest.mark.asyncio
    async def test_update_card_applies_fields(self) -> None:
        """Existing attributes are updated from the data dict."""
        session = _mock_session()
        card = _make_card(name="old-name")
        session.get.return_value = card

        result = await A2APublisher.update_card(
            session, CARD_ID, {"name": "new-name", "version": "2.0.0"}
        )

        assert result is not None
        assert result.name == "new-name"
        assert result.version == "2.0.0"
        assert result.updated_at is not None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_card_ignores_unknown_fields(self) -> None:
        """Fields not present on A2AAgentCard are silently skipped."""
        session = _mock_session()
        card = _make_card()
        session.get.return_value = card

        result = await A2APublisher.update_card(
            session, CARD_ID, {"nonexistent_field": "value"}
        )

        assert result is not None
        assert not hasattr(result, "nonexistent_field")

    @pytest.mark.asyncio
    async def test_update_card_not_found(self) -> None:
        """Returns None when card doesn't exist."""
        session = _mock_session()
        session.get.return_value = None

        result = await A2APublisher.update_card(session, CARD_ID, {"name": "x"})

        assert result is None
        session.commit.assert_not_awaited()


class TestA2APublisherUnpublishCard:
    """Tests for A2APublisher.unpublish_card."""

    @pytest.mark.asyncio
    async def test_unpublish_deletes_and_returns_true(self) -> None:
        session = _mock_session()
        card = _make_card()
        session.get.return_value = card

        result = await A2APublisher.unpublish_card(session, CARD_ID)

        assert result is True
        session.delete.assert_awaited_once_with(card)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unpublish_not_found_returns_false(self) -> None:
        session = _mock_session()
        session.get.return_value = None

        result = await A2APublisher.unpublish_card(session, CARD_ID)

        assert result is False
        session.delete.assert_not_awaited()
        session.commit.assert_not_awaited()


class TestA2APublisherGetCard:
    """Tests for A2APublisher.get_card."""

    @pytest.mark.asyncio
    async def test_get_card_found(self) -> None:
        session = _mock_session()
        card = _make_card()
        session.get.return_value = card

        result = await A2APublisher.get_card(session, CARD_ID)

        assert result is card

    @pytest.mark.asyncio
    async def test_get_card_not_found(self) -> None:
        session = _mock_session()
        session.get.return_value = None

        result = await A2APublisher.get_card(session, CARD_ID)

        assert result is None


class TestA2APublisherListPublished:
    """Tests for A2APublisher.list_published."""

    @pytest.mark.asyncio
    async def test_list_published_returns_tuple(self) -> None:
        session = _mock_session()
        card = _make_card(direction="outbound")
        count_result = _mock_exec_result([card])
        page_result = _mock_exec_result([card])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        cards, total = await A2APublisher.list_published(session)

        assert total == 1
        assert cards == [card]

    @pytest.mark.asyncio
    async def test_list_published_empty(self) -> None:
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        cards, total = await A2APublisher.list_published(session)

        assert total == 0
        assert cards == []


class TestA2APublisherGetWellKnownCard:
    """Tests for A2APublisher.get_well_known_card."""

    @pytest.mark.asyncio
    async def test_get_well_known_card_found(self) -> None:
        session = _mock_session()
        card = _make_card(direction="outbound", agent_id=AGENT_ID)
        exec_result = _mock_exec_result([card])
        session.exec.return_value = exec_result

        result = await A2APublisher.get_well_known_card(session, AGENT_ID)

        assert result is card

    @pytest.mark.asyncio
    async def test_get_well_known_card_not_found(self) -> None:
        session = _mock_session()
        exec_result = _mock_exec_result([])
        session.exec.return_value = exec_result

        result = await A2APublisher.get_well_known_card(session, AGENT_ID)

        assert result is None


# ── Edge Case / Cross-Cutting Tests ─────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_send_message_empty_content(self) -> None:
        """Empty string content is valid."""
        session = _mock_session()

        result = await A2AClient.send_message(
            session, task_id=TASK_ID, role="user", content=""
        )

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_create_task_empty_input_data(self) -> None:
        """Empty dict input_data is valid."""
        session = _mock_session()

        result = await A2AClient.create_task(
            session, agent_card_id=CARD_ID, input_data={}
        )

        assert result.input_data == {}

    @pytest.mark.asyncio
    async def test_update_card_empty_data_dict(self) -> None:
        """Updating with empty data dict still commits (updates updated_at)."""
        session = _mock_session()
        card = _make_card()
        session.get.return_value = card

        result = await A2APublisher.update_card(session, CARD_ID, {})

        assert result is not None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discover_with_is_active_filter(self) -> None:
        """is_active filter is passed through to query."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        entries, total = await A2AClient.discover_agents(
            session, is_active=True
        )

        assert total == 0
        assert entries == []

    @pytest.mark.asyncio
    async def test_list_tasks_with_all_filters(self) -> None:
        """All optional filters can be supplied together."""
        session = _mock_session()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        tasks, total = await A2AClient.list_tasks(
            session,
            agent_card_id=CARD_ID,
            status="completed",
            direction="outbound",
            limit=10,
            offset=5,
        )

        assert total == 0
        assert tasks == []

    @pytest.mark.asyncio
    async def test_update_task_status_output_data_none(self) -> None:
        """When output_data is not passed, task.output_data is unchanged."""
        session = _mock_session()
        task = _make_task()
        task.output_data = None
        session.get.return_value = task

        result = await A2AClient.update_task_status(
            session, TASK_ID, status="working"
        )

        assert result is not None
        assert result.output_data is None
