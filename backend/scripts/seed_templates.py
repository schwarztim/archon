"""Seed the database with 21 starter templates for the Template Gallery.

Usage:
    cd ~/Scripts/Archon
    PYTHONPATH=backend python -m backend.scripts.seed_templates

Or import and call ``seed()`` from application startup.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

# Ensure backend package is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session_factory, engine  # noqa: E402
from app.models import Template  # noqa: E402

logger = logging.getLogger(__name__)

SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

SEED_TEMPLATES: list[dict] = [
    # ── Customer Support (3) ──────────────────────────────────────
    {
        "name": "Customer Support Bot",
        "description": "AI-powered support agent that handles common inquiries, tracks tickets, and escalates complex issues to human agents.",
        "category": "Customer Support",
        "tags": ["support", "chat", "tickets"],
        "definition": {"model": "gpt-4o", "temperature": 0.5, "tools": ["web_search", "api_caller"]},
    },
    {
        "name": "Refund Processor",
        "description": "Automates refund request processing with policy checks, order validation, and approval workflows.",
        "category": "Customer Support",
        "tags": ["refunds", "automation"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["api_caller", "database_query"]},
    },
    {
        "name": "FAQ Auto-Responder",
        "description": "Answers frequently asked questions using a curated knowledge base with context-aware responses.",
        "category": "Customer Support",
        "tags": ["faq", "knowledge-base"],
        "definition": {"model": "gpt-4o-mini", "temperature": 0.4, "tools": ["web_search"]},
    },
    # ── Data Analysis (3) ─────────────────────────────────────────
    {
        "name": "Sales Data Analyst",
        "description": "Analyzes sales data, generates reports, identifies trends, and provides actionable business insights.",
        "category": "Data Analysis",
        "tags": ["analytics", "reports", "sales"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["code_interpreter", "database_query"]},
    },
    {
        "name": "Log Analyzer",
        "description": "Parses and analyzes application logs to detect anomalies, errors, and performance bottlenecks.",
        "category": "Data Analysis",
        "tags": ["logs", "monitoring"],
        "definition": {"model": "gpt-4o", "temperature": 0.2, "tools": ["file_reader", "code_interpreter"]},
    },
    {
        "name": "Survey Insights",
        "description": "Processes survey responses, performs sentiment analysis, and generates executive summaries.",
        "category": "Data Analysis",
        "tags": ["surveys", "sentiment"],
        "definition": {"model": "gpt-4o-mini", "temperature": 0.4, "tools": ["code_interpreter"]},
    },
    # ── Content Generation (4) ────────────────────────────────────
    {
        "name": "Blog Writer",
        "description": "Generates SEO-optimized blog posts with research, outlines, and multi-draft revision workflows.",
        "category": "Content Generation",
        "tags": ["blog", "seo", "writing"],
        "definition": {"model": "gpt-4o", "temperature": 0.7, "tools": ["web_search"]},
    },
    {
        "name": "Social Media Manager",
        "description": "Creates and schedules social media content across platforms with tone and brand consistency.",
        "category": "Content Generation",
        "tags": ["social", "marketing"],
        "definition": {"model": "gpt-4o-mini", "temperature": 0.8, "tools": ["web_search", "api_caller"]},
    },
    {
        "name": "Email Campaign Drafter",
        "description": "Generates personalized email campaigns with A/B testing variants and performance tracking.",
        "category": "Content Generation",
        "tags": ["email", "campaigns"],
        "definition": {"model": "gpt-4o", "temperature": 0.6, "tools": ["api_caller"]},
    },
    {
        "name": "Newsletter Curator",
        "description": "Curates and summarizes industry news into formatted newsletter content.",
        "category": "Content Generation",
        "tags": ["newsletter", "curation"],
        "definition": {"model": "gpt-4o-mini", "temperature": 0.5, "tools": ["web_search"]},
    },
    # ── Code Assistant (4) ────────────────────────────────────────
    {
        "name": "Code Reviewer",
        "description": "Reviews pull requests, identifies bugs, security vulnerabilities, and suggests improvements.",
        "category": "Code Assistant",
        "tags": ["code-review", "security"],
        "definition": {"model": "gpt-4o", "temperature": 0.2, "tools": ["code_interpreter", "file_reader"]},
    },
    {
        "name": "Test Generator",
        "description": "Automatically generates unit and integration tests for codebases with high coverage targets.",
        "category": "Code Assistant",
        "tags": ["testing", "automation"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["code_interpreter", "file_reader"]},
    },
    {
        "name": "Documentation Writer",
        "description": "Generates API documentation, README files, and inline code comments from source code.",
        "category": "Code Assistant",
        "tags": ["docs", "api"],
        "definition": {"model": "gpt-4o", "temperature": 0.4, "tools": ["file_reader"]},
    },
    {
        "name": "Refactor Assistant",
        "description": "Suggests and applies code refactoring patterns to improve code quality and maintainability.",
        "category": "Code Assistant",
        "tags": ["refactoring", "quality"],
        "definition": {"model": "gpt-4o", "temperature": 0.2, "tools": ["code_interpreter", "file_reader"]},
    },
    # ── Research (3) ──────────────────────────────────────────────
    {
        "name": "Research Assistant",
        "description": "Searches academic papers, summarizes findings, and generates literature review drafts.",
        "category": "Research",
        "tags": ["academic", "papers"],
        "definition": {"model": "gpt-4o", "temperature": 0.5, "tools": ["web_search"]},
    },
    {
        "name": "Competitive Intelligence",
        "description": "Monitors competitors, analyzes market positioning, and generates comparison reports.",
        "category": "Research",
        "tags": ["market", "intelligence"],
        "definition": {"model": "gpt-4o", "temperature": 0.4, "tools": ["web_search", "api_caller"]},
    },
    {
        "name": "Patent Analyzer",
        "description": "Analyzes patent filings, identifies prior art, and summarizes technical claims.",
        "category": "Research",
        "tags": ["patents", "legal"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["web_search", "file_reader"]},
    },
    # ── DevOps (3) ────────────────────────────────────────────────
    {
        "name": "CI/CD Monitor",
        "description": "Monitors CI/CD pipelines, detects failures, and suggests fixes based on error patterns.",
        "category": "DevOps",
        "tags": ["ci-cd", "monitoring"],
        "definition": {"model": "gpt-4o", "temperature": 0.2, "tools": ["api_caller", "code_interpreter"]},
    },
    {
        "name": "Incident Responder",
        "description": "Automates incident response with runbook execution, status page updates, and escalation.",
        "category": "DevOps",
        "tags": ["incidents", "runbooks"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["api_caller", "email_sender"]},
    },
    {
        "name": "Infrastructure Advisor",
        "description": "Analyzes infrastructure costs, recommends optimizations, and generates provisioning plans.",
        "category": "DevOps",
        "tags": ["infra", "cost"],
        "definition": {"model": "gpt-4o", "temperature": 0.3, "tools": ["api_caller", "database_query"]},
    },
    # ── Custom (1) ────────────────────────────────────────────────
    {
        "name": "Custom Workflow",
        "description": "Blank template for building custom agent workflows from scratch.",
        "category": "Custom",
        "tags": ["custom", "blank"],
        "definition": {"model": "gpt-4o", "temperature": 0.7, "tools": []},
    },
]


async def seed() -> int:
    """Insert seed templates that don't already exist. Returns insert count."""
    async with async_session_factory() as session:
        # Build set of existing template names for idempotency
        from sqlmodel import select

        result = await session.exec(select(Template.name))
        existing_names: set[str] = set(result.all())

        inserted = 0
        for tpl in SEED_TEMPLATES:
            if tpl["name"] in existing_names:
                continue
            template = Template(
                name=tpl["name"],
                description=tpl["description"],
                category=tpl["category"],
                tags=tpl["tags"],
                definition=tpl["definition"],
                author_id=SYSTEM_USER_ID,
            )
            session.add(template)
            inserted += 1

        if inserted:
            await session.commit()
            logger.info("Seeded %d templates", inserted)
        else:
            logger.info("All seed templates already exist — nothing to do")

    return inserted


async def _main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO)
    count = await seed()
    print(f"Seeded {count} templates (total available: {len(SEED_TEMPLATES)})")


if __name__ == "__main__":
    asyncio.run(_main())
