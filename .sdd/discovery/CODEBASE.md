# Archon — Codebase Discovery

AI orchestration platform for building, routing, and managing multi-agent workflows.

## Directory Structure

```
Archon/
├── agents/              # Agent rules, prompts, swarm config
├── backend/
│   ├── app/
│   │   ├── main.py      # FastAPI entry point
│   │   ├── config.py    # Pydantic-settings (ARCHON_ prefix)
│   │   ├── database.py  # SQLModel / DB session
│   │   ├── models/      # SQLModel ORM models
│   │   ├── routes/      # FastAPI routers (/api/v1/)
│   │   ├── services/    # Business logic layer
│   │   ├── interfaces/  # External service abstractions
│   │   ├── langgraph/   # LangGraph agent graphs
│   │   └── websocket/   # WebSocket handlers
│   ├── alembic/         # DB migrations
│   ├── tests/           # Backend pytest tests
│   └── Dockerfile
├── contracts/
│   └── openapi.yaml     # API contract (source of truth)
├── frontend/            # React 19 + TypeScript (scaffolded)
├── infra/               # Terraform, Helm, K8s manifests
├── docs/                # ADRs, architecture, contributing
├── data/                # Data assets (placeholder)
├── integrations/        # External integrations (placeholder)
├── security/            # Security config (placeholder)
├── ops/                 # Operational tooling (placeholder)
├── tests/               # Top-level test directory (placeholder)
├── docker-compose.yaml  # Local dev stack
└── Makefile             # Dev commands
```

## Tech Stack

| Layer     | Technology                              |
|-----------|-----------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLModel, Alembic |
| Agents    | LangGraph                               |
| Frontend  | React 19, TypeScript, shadcn/ui, Tailwind |
| Database  | PostgreSQL                              |
| Cache     | Redis                                   |
| Infra     | Docker, Kubernetes, Terraform, Helm     |

## Key Entry Points

- **API server:** `backend/app/main.py`
- **API contract:** `contracts/openapi.yaml`
- **Agent rules:** `agents/AGENT_RULES.md`
- **Dev stack:** `docker-compose.yaml`

## Current State

Phase 0 vertical slice complete. Backend skeleton with FastAPI routing, SQLModel ORM, Alembic migrations, and LangGraph agent layer in place. Frontend scaffolded. Infrastructure templates present.
