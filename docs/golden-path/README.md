# Golden Path Examples

> Reference implementations of every canonical pattern. Agents MUST follow these patterns exactly.
> See individual example files for copy-paste-ready code.

## Available Examples

| File | Pattern | Used By |
|------|---------|---------|
| `router-example.py` | FastAPI router with auth, validation, pagination, error handling | All backend agents |
| `service-example.py` | Service layer with dependency injection, logging, error handling | All backend agents |
| `test-example.py` | pytest test with fixtures, factories, assertions | All agents |
| `model-example.py` | SQLModel with relationships, timestamps, soft delete | All backend agents |
| `04-authenticated-endpoint.md` | FastAPI endpoint with JWT auth, RBAC, tenant isolation, audit | All backend agents |
| `05-vault-credential-access.md` | SecretsManager: static, dynamic, PKI, rotation with tenant scope | All backend agents |

## Rules

1. When in doubt, copy the golden path pattern
2. If you need to deviate, get Orchestrator approval first
3. These patterns encode all ADR decisions in working code
4. Update golden path files if an ADR changes (Orchestrator only)
