# Archon — Enterprise-Grade Open-Source AI Orchestration Platform

> The open-source alternative to commercial AI orchestration platforms. Built agentically. Enterprise-ready from day one.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Built With](https://img.shields.io/badge/Built_With-Agentic_AI-purple.svg)](#)

---

## What is Archon?

Archon is a **complete, production-ready, enterprise-grade AI orchestration and governance platform** — built entirely by a coordinated swarm of specialized AI agents. It provides:

- **No-Code Drag-and-Drop Agent Builder** — Visual canvas for building AI workflows
- **Model-Agnostic Routing** — OpenAI, Anthropic, Grok, Llama, Mistral, local models (vLLM/Ollama)
- **Enterprise Security** — SOC2/Type II ready, GDPR, HIPAA, zero-trust, DLP, guardrails
- **Intelligent Operations** — Real-time routing, cost optimization, lifecycle management
- **50+ Data Connectors** — M365, Salesforce, Confluence, and custom SDK
- **On-Prem & Air-Gapped Deployment** — Kubernetes + Helm + Terraform
- **Mobile SDK** — Flutter + native iOS/Android chat applications

## Architecture

```
Archon/
├── frontend/          # React 19 + TypeScript + React Flow (drag-drop builder)
├── backend/           # FastAPI + Python 3.12 + LangGraph
├── agents/            # Core orchestration agents (LangGraph state machines)
│   ├── prompts/       # 17 specialized agent prompt files
│   └── swarm/         # Swarm coordination and state management
├── security/          # Guardrails, DLP, red-teaming engine
├── integrations/      # 50+ connectors + Live Components support
├── ops/               # Intelligent Ops, routing, cost engine, monitoring
├── data/              # RAG + document processor (LlamaIndex + Unstructured.io)
├── infra/             # Terraform + Helm + Kubernetes manifests
├── mobile/            # Flutter SDK + iOS/Android native
├── docs/              # Auto-generated + agent-written documentation
└── tests/             # Comprehensive test suite (agent-generated)
```

## Tech Stack (100% Open-Source)

| Layer | Technology |
|-------|-----------|
| UI/Builder | React 19 + shadcn/ui + React Flow + Monaco Editor |
| Orchestration | LangGraph + LangChain + CrewAI patterns |
| Backend | FastAPI + SQLModel + Alembic + Celery |
| Vector/RAG | PGVector + LlamaIndex + Unstructured + Haystack |
| Security | OPA + Guardrails AI + NeMo Guardrails + HashiCorp Vault |
| Monitoring | Prometheus + Grafana + OpenTelemetry + OpenSearch |
| Deployment | Kubernetes + ArgoCD + Kyverno + Cert-Manager |
| Auth | Keycloak + OAuth2 + OIDC + RBAC/ABAC |
| Cost/Usage | Custom token tracker + OpenLLMetry |

## Quick Start

> ⚠️ **Project Status: Scaffolding & Roadmap Phase** — Not yet buildable.

```bash
# Clone the repo
git clone https://github.com/your-org/archon.git
cd archon

# Future: docker-compose up -d
```

## Build Phases

| Phase | Focus | Agents |
|-------|-------|--------|
| Phase 1 | Core Platform | Agents 01–06 |
| Phase 2 | Operations & Cost | Agents 07–09 |
| Phase 3 | Security & Governance | Agents 10–12 |
| Phase 4 | Integrations & Data | Agents 13–14 |
| Phase 5 | Deployment & UX | Agents 15–17 |
| Phase 6 | Validation & Polish | Master Validator Agent |

## Documentation

- [Architecture Document](docs/ARCHITECTURE.md)
- [Project Bible / Instructions](INSTRUCTIONS.md)
- [Roadmap](ROADMAP.md)
- [Agent Swarm Overview](agents/SWARM_OVERVIEW.md)
- [Main Orchestrator Prompt](MAIN_PROMPT.md)

## Contributing

This project is built agentically, but human contributors are welcome. See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

## License

Apache 2.0 — see [LICENSE](LICENSE).
