# ADR-004: Orchestration Engine

> **Status**: ACCEPTED
> **Date**: 2026-02-16
> **Decision**: LangGraph for agent orchestration, LiteLLM as the model gateway, Celery + Redis for async task execution and state caching.

## Context

Archon orchestrates AI agents that collaborate on multi-step tasks. The orchestration engine must support complex control flow (branching, looping, human-in-the-loop), work with many LLM providers, and handle both short-lived API-bound tasks and long-running background jobs. Agents need a shared state mechanism and reliable task queuing.

## Decision

### Agent Orchestration: LangGraph

- Agents are defined as LangGraph `StateGraph` instances. Each graph declares nodes (agent steps), edges (transitions), and a typed state schema.
- LangGraph provides built-in support for cycles, conditional branching, parallel fan-out, and human-in-the-loop interrupts.
- State is checkpointed between nodes, enabling pause/resume and retry of failed steps.
- LangGraph was chosen over raw LangChain chains (too linear), CrewAI (less control over graph topology), and AutoGen (heavier runtime).

### Model Gateway: LiteLLM

- All LLM calls go through LiteLLM, which provides a unified OpenAI-compatible interface to 100+ model providers (OpenAI, Anthropic, Azure, Ollama, etc.).
- Model selection is configured per-agent via `ARCHON_`-prefixed environment variables or tenant settings. No vendor lock-in.
- LiteLLM handles retries, fallbacks, and spend tracking at the gateway level.

### Task Execution: Celery + Redis

- Short-lived agent runs (<30s) execute inline within the FastAPI request/response cycle (async).
- Long-running agent runs are dispatched to Celery workers via Redis as the message broker.
- Celery tasks are idempotent and report progress via Redis pub/sub, which the API exposes as SSE streams.
- Task results are stored in Redis with a configurable TTL (default: 24h).

### State & Caching: Redis

- Redis serves three roles: Celery broker, LangGraph state cache, and general application cache.
- Agent execution state is cached in Redis during runs and persisted to PostgreSQL on completion.
- Cache keys are namespaced by tenant to prevent cross-tenant leakage.

### Configuration

```
ARCHON_REDIS_URL=redis://host:6379/0
ARCHON_CELERY_BROKER_URL=redis://host:6379/1
ARCHON_LITELLM_API_BASE=http://litellm:4000
ARCHON_DEFAULT_MODEL=gpt-4o
```

## Consequences

- LangGraph gives fine-grained control over agent workflows without sacrificing composability
- LiteLLM decouples agent logic from specific LLM providers, enabling easy model swaps
- Celery handles long-running tasks reliably with built-in retry and monitoring (Flower)
- Redis as a multi-purpose store simplifies infrastructure but requires careful memory management
- Team must learn LangGraph's StateGraph API, which has a steeper curve than simple chains
- Celery adds worker process management; tasks must be designed to be idempotent
