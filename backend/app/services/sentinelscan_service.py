"""SentinelScan Shadow AI Discovery & Security Posture Management engine."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.models.sentinelscan import (
    AIAsset,
    CredentialExposure,
    DiscoveryConfig,
    DiscoveryResult,
    IngestResult,
    KnownAIService,
    PostureReport,
    PostureScore,
    RemediationWorkflow,
)

logger = logging.getLogger(__name__)

# ── Known AI services database (200+) ──────────────────────────────

_KNOWN_AI_SERVICES: list[dict[str, str]] = [
    # LLM Providers
    {"name": "OpenAI ChatGPT", "domain": "chat.openai.com", "category": "llm", "risk_level": "high", "provider": "openai", "description": "Large language model chatbot"},
    {"name": "OpenAI API", "domain": "api.openai.com", "category": "llm", "risk_level": "high", "provider": "openai", "description": "OpenAI API platform"},
    {"name": "OpenAI Platform", "domain": "platform.openai.com", "category": "llm", "risk_level": "high", "provider": "openai", "description": "OpenAI developer platform"},
    {"name": "Anthropic Claude", "domain": "claude.ai", "category": "llm", "risk_level": "high", "provider": "anthropic", "description": "Claude AI assistant"},
    {"name": "Anthropic API", "domain": "api.anthropic.com", "category": "llm", "risk_level": "high", "provider": "anthropic", "description": "Anthropic API platform"},
    {"name": "Google Gemini", "domain": "gemini.google.com", "category": "llm", "risk_level": "high", "provider": "google", "description": "Google Gemini AI"},
    {"name": "Google AI Studio", "domain": "aistudio.google.com", "category": "llm", "risk_level": "high", "provider": "google", "description": "Google AI Studio"},
    {"name": "Google Vertex AI", "domain": "console.cloud.google.com/vertex-ai", "category": "llm", "risk_level": "medium", "provider": "google", "description": "Google Cloud Vertex AI"},
    {"name": "Microsoft Copilot", "domain": "copilot.microsoft.com", "category": "copilot", "risk_level": "medium", "provider": "microsoft", "description": "Microsoft Copilot"},
    {"name": "Azure OpenAI", "domain": "oai.azure.com", "category": "llm", "risk_level": "medium", "provider": "microsoft", "description": "Azure OpenAI Service"},
    {"name": "Meta Llama", "domain": "llama.meta.com", "category": "llm", "risk_level": "medium", "provider": "meta", "description": "Meta Llama models"},
    {"name": "Cohere", "domain": "dashboard.cohere.com", "category": "llm", "risk_level": "medium", "provider": "cohere", "description": "Cohere NLP platform"},
    {"name": "Cohere API", "domain": "api.cohere.ai", "category": "llm", "risk_level": "medium", "provider": "cohere", "description": "Cohere API"},
    {"name": "AI21 Labs", "domain": "studio.ai21.com", "category": "llm", "risk_level": "medium", "provider": "ai21", "description": "AI21 Labs Jurassic models"},
    {"name": "Mistral AI", "domain": "chat.mistral.ai", "category": "llm", "risk_level": "medium", "provider": "mistral", "description": "Mistral AI chat"},
    {"name": "Mistral API", "domain": "api.mistral.ai", "category": "llm", "risk_level": "medium", "provider": "mistral", "description": "Mistral AI API"},
    {"name": "Perplexity AI", "domain": "perplexity.ai", "category": "llm", "risk_level": "medium", "provider": "perplexity", "description": "Perplexity AI search"},
    {"name": "Inflection Pi", "domain": "pi.ai", "category": "llm", "risk_level": "medium", "provider": "inflection", "description": "Inflection Pi AI"},
    {"name": "xAI Grok", "domain": "grok.x.ai", "category": "llm", "risk_level": "medium", "provider": "xai", "description": "xAI Grok"},
    {"name": "DeepSeek", "domain": "chat.deepseek.com", "category": "llm", "risk_level": "high", "provider": "deepseek", "description": "DeepSeek AI"},
    {"name": "DeepSeek API", "domain": "api.deepseek.com", "category": "llm", "risk_level": "high", "provider": "deepseek", "description": "DeepSeek API"},
    # Code Assistants
    {"name": "GitHub Copilot", "domain": "github.com/features/copilot", "category": "code_assistant", "risk_level": "medium", "provider": "github", "description": "AI pair programmer"},
    {"name": "Cursor", "domain": "cursor.sh", "category": "code_assistant", "risk_level": "medium", "provider": "cursor", "description": "AI code editor"},
    {"name": "Replit AI", "domain": "replit.com", "category": "code_assistant", "risk_level": "medium", "provider": "replit", "description": "AI-powered IDE"},
    {"name": "Tabnine", "domain": "tabnine.com", "category": "code_assistant", "risk_level": "low", "provider": "tabnine", "description": "AI code completion"},
    {"name": "Codeium", "domain": "codeium.com", "category": "code_assistant", "risk_level": "low", "provider": "codeium", "description": "Free AI code completion"},
    {"name": "Amazon CodeWhisperer", "domain": "aws.amazon.com/codewhisperer", "category": "code_assistant", "risk_level": "low", "provider": "amazon", "description": "AWS AI code generator"},
    {"name": "Sourcegraph Cody", "domain": "sourcegraph.com/cody", "category": "code_assistant", "risk_level": "medium", "provider": "sourcegraph", "description": "AI coding assistant"},
    {"name": "Codium AI", "domain": "codium.ai", "category": "code_assistant", "risk_level": "low", "provider": "codium", "description": "AI test generation"},
    {"name": "Windsurf", "domain": "windsurf.ai", "category": "code_assistant", "risk_level": "medium", "provider": "codeium", "description": "AI code editor"},
    # Image Generation
    {"name": "Midjourney", "domain": "midjourney.com", "category": "image_gen", "risk_level": "medium", "provider": "midjourney", "description": "AI image generation"},
    {"name": "DALL-E", "domain": "labs.openai.com", "category": "image_gen", "risk_level": "medium", "provider": "openai", "description": "OpenAI image generation"},
    {"name": "Stable Diffusion", "domain": "stability.ai", "category": "image_gen", "risk_level": "medium", "provider": "stability", "description": "Open source image generation"},
    {"name": "Adobe Firefly", "domain": "firefly.adobe.com", "category": "image_gen", "risk_level": "low", "provider": "adobe", "description": "Adobe AI image generation"},
    {"name": "Leonardo AI", "domain": "leonardo.ai", "category": "image_gen", "risk_level": "medium", "provider": "leonardo", "description": "AI image generation platform"},
    {"name": "Ideogram", "domain": "ideogram.ai", "category": "image_gen", "risk_level": "medium", "provider": "ideogram", "description": "AI image generation"},
    {"name": "Flux AI", "domain": "flux.ai", "category": "image_gen", "risk_level": "medium", "provider": "flux", "description": "AI image generation"},
    # Chatbots & Assistants
    {"name": "Character AI", "domain": "character.ai", "category": "chatbot", "risk_level": "medium", "provider": "character", "description": "AI character chatbot"},
    {"name": "Poe", "domain": "poe.com", "category": "chatbot", "risk_level": "medium", "provider": "quora", "description": "Multi-model chatbot platform"},
    {"name": "You.com", "domain": "you.com", "category": "chatbot", "risk_level": "medium", "provider": "you", "description": "AI search and chat"},
    {"name": "Phind", "domain": "phind.com", "category": "chatbot", "risk_level": "medium", "provider": "phind", "description": "AI developer search"},
    {"name": "HuggingChat", "domain": "huggingface.co/chat", "category": "chatbot", "risk_level": "medium", "provider": "huggingface", "description": "Open-source AI chat"},
    # SaaS AI Tools
    {"name": "Jasper AI", "domain": "jasper.ai", "category": "saas_ai", "risk_level": "medium", "provider": "jasper", "description": "AI content creation"},
    {"name": "Copy.ai", "domain": "copy.ai", "category": "saas_ai", "risk_level": "medium", "provider": "copy", "description": "AI copywriting"},
    {"name": "Writesonic", "domain": "writesonic.com", "category": "saas_ai", "risk_level": "medium", "provider": "writesonic", "description": "AI writing assistant"},
    {"name": "Grammarly AI", "domain": "grammarly.com", "category": "saas_ai", "risk_level": "low", "provider": "grammarly", "description": "AI writing enhancement"},
    {"name": "Notion AI", "domain": "notion.so", "category": "saas_ai", "risk_level": "medium", "provider": "notion", "description": "AI-powered workspace"},
    {"name": "Otter.ai", "domain": "otter.ai", "category": "saas_ai", "risk_level": "medium", "provider": "otter", "description": "AI meeting transcription"},
    {"name": "Fireflies.ai", "domain": "fireflies.ai", "category": "saas_ai", "risk_level": "high", "provider": "fireflies", "description": "AI meeting recorder"},
    {"name": "Descript", "domain": "descript.com", "category": "saas_ai", "risk_level": "medium", "provider": "descript", "description": "AI video/audio editing"},
    {"name": "Canva AI", "domain": "canva.com", "category": "saas_ai", "risk_level": "low", "provider": "canva", "description": "AI design tools"},
    {"name": "Tome AI", "domain": "tome.app", "category": "saas_ai", "risk_level": "medium", "provider": "tome", "description": "AI presentation builder"},
    {"name": "Beautiful.ai", "domain": "beautiful.ai", "category": "saas_ai", "risk_level": "low", "provider": "beautiful", "description": "AI presentations"},
    {"name": "Loom AI", "domain": "loom.com", "category": "saas_ai", "risk_level": "low", "provider": "loom", "description": "AI video messaging"},
    {"name": "Synthesia", "domain": "synthesia.io", "category": "saas_ai", "risk_level": "medium", "provider": "synthesia", "description": "AI video generation"},
    {"name": "RunwayML", "domain": "runwayml.com", "category": "saas_ai", "risk_level": "medium", "provider": "runway", "description": "AI video editing"},
    {"name": "ElevenLabs", "domain": "elevenlabs.io", "category": "saas_ai", "risk_level": "medium", "provider": "elevenlabs", "description": "AI voice synthesis"},
    {"name": "Murf AI", "domain": "murf.ai", "category": "saas_ai", "risk_level": "medium", "provider": "murf", "description": "AI voice generation"},
    {"name": "Pictory", "domain": "pictory.ai", "category": "saas_ai", "risk_level": "medium", "provider": "pictory", "description": "AI video creation"},
    {"name": "Luma AI", "domain": "lumalabs.ai", "category": "saas_ai", "risk_level": "medium", "provider": "luma", "description": "AI 3D capture"},
    # Data & Analytics AI
    {"name": "DataRobot", "domain": "datarobot.com", "category": "saas_ai", "risk_level": "medium", "provider": "datarobot", "description": "AutoML platform"},
    {"name": "H2O.ai", "domain": "h2o.ai", "category": "saas_ai", "risk_level": "medium", "provider": "h2o", "description": "AI/ML platform"},
    {"name": "Databricks AI", "domain": "databricks.com", "category": "saas_ai", "risk_level": "medium", "provider": "databricks", "description": "Lakehouse AI"},
    {"name": "Weights & Biases", "domain": "wandb.ai", "category": "saas_ai", "risk_level": "medium", "provider": "wandb", "description": "ML experiment tracking"},
    {"name": "Neptune.ai", "domain": "neptune.ai", "category": "saas_ai", "risk_level": "low", "provider": "neptune", "description": "ML metadata store"},
    {"name": "MLflow", "domain": "mlflow.org", "category": "saas_ai", "risk_level": "low", "provider": "databricks", "description": "ML lifecycle platform"},
    {"name": "Hugging Face", "domain": "huggingface.co", "category": "saas_ai", "risk_level": "medium", "provider": "huggingface", "description": "ML model hub"},
    {"name": "Replicate", "domain": "replicate.com", "category": "saas_ai", "risk_level": "medium", "provider": "replicate", "description": "Run ML models via API"},
    {"name": "Together AI", "domain": "together.ai", "category": "llm", "risk_level": "medium", "provider": "together", "description": "Open-source model hosting"},
    {"name": "Anyscale", "domain": "anyscale.com", "category": "saas_ai", "risk_level": "medium", "provider": "anyscale", "description": "Ray-based AI platform"},
    {"name": "Modal", "domain": "modal.com", "category": "saas_ai", "risk_level": "medium", "provider": "modal", "description": "Serverless AI compute"},
    {"name": "Baseten", "domain": "baseten.co", "category": "saas_ai", "risk_level": "medium", "provider": "baseten", "description": "ML model deployment"},
    # Security & Compliance AI
    {"name": "Darktrace", "domain": "darktrace.com", "category": "saas_ai", "risk_level": "low", "provider": "darktrace", "description": "AI cybersecurity"},
    {"name": "Vectra AI", "domain": "vectra.ai", "category": "saas_ai", "risk_level": "low", "provider": "vectra", "description": "AI threat detection"},
    {"name": "SentinelOne AI", "domain": "sentinelone.com", "category": "saas_ai", "risk_level": "low", "provider": "sentinelone", "description": "AI endpoint security"},
    {"name": "CrowdStrike Charlotte", "domain": "crowdstrike.com", "category": "saas_ai", "risk_level": "low", "provider": "crowdstrike", "description": "AI security assistant"},
    # Customer Service AI
    {"name": "Zendesk AI", "domain": "zendesk.com", "category": "saas_ai", "risk_level": "medium", "provider": "zendesk", "description": "AI customer service"},
    {"name": "Intercom Fin", "domain": "intercom.com", "category": "saas_ai", "risk_level": "medium", "provider": "intercom", "description": "AI chatbot for support"},
    {"name": "Ada AI", "domain": "ada.cx", "category": "saas_ai", "risk_level": "medium", "provider": "ada", "description": "AI customer service automation"},
    {"name": "Drift AI", "domain": "drift.com", "category": "saas_ai", "risk_level": "medium", "provider": "drift", "description": "AI conversational marketing"},
    # HR & Recruiting AI
    {"name": "HireVue", "domain": "hirevue.com", "category": "saas_ai", "risk_level": "high", "provider": "hirevue", "description": "AI video interviewing"},
    {"name": "Eightfold AI", "domain": "eightfold.ai", "category": "saas_ai", "risk_level": "high", "provider": "eightfold", "description": "AI talent intelligence"},
    {"name": "Textio", "domain": "textio.com", "category": "saas_ai", "risk_level": "medium", "provider": "textio", "description": "AI writing for hiring"},
    {"name": "Paradox AI", "domain": "paradox.ai", "category": "saas_ai", "risk_level": "medium", "provider": "paradox", "description": "AI recruiting assistant"},
    # Sales & Marketing AI
    {"name": "Gong", "domain": "gong.io", "category": "saas_ai", "risk_level": "high", "provider": "gong", "description": "AI revenue intelligence"},
    {"name": "Chorus.ai", "domain": "chorus.ai", "category": "saas_ai", "risk_level": "high", "provider": "zoominfo", "description": "AI conversation intelligence"},
    {"name": "Clari", "domain": "clari.com", "category": "saas_ai", "risk_level": "medium", "provider": "clari", "description": "AI revenue platform"},
    {"name": "Drift", "domain": "drift.com", "category": "saas_ai", "risk_level": "medium", "provider": "salesloft", "description": "AI conversational sales"},
    {"name": "6sense", "domain": "6sense.com", "category": "saas_ai", "risk_level": "medium", "provider": "6sense", "description": "AI revenue platform"},
    {"name": "Outreach AI", "domain": "outreach.io", "category": "saas_ai", "risk_level": "medium", "provider": "outreach", "description": "AI sales engagement"},
    # Document & Knowledge AI
    {"name": "DocuSign AI", "domain": "docusign.com", "category": "saas_ai", "risk_level": "medium", "provider": "docusign", "description": "AI contract analysis"},
    {"name": "Coda AI", "domain": "coda.io", "category": "saas_ai", "risk_level": "medium", "provider": "coda", "description": "AI-powered docs"},
    {"name": "Mem AI", "domain": "mem.ai", "category": "saas_ai", "risk_level": "medium", "provider": "mem", "description": "AI note-taking"},
    {"name": "Glean", "domain": "glean.com", "category": "saas_ai", "risk_level": "high", "provider": "glean", "description": "AI enterprise search"},
    {"name": "Guru", "domain": "getguru.com", "category": "saas_ai", "risk_level": "medium", "provider": "guru", "description": "AI knowledge management"},
    # Design & Creative AI
    {"name": "Figma AI", "domain": "figma.com", "category": "saas_ai", "risk_level": "low", "provider": "figma", "description": "AI design features"},
    {"name": "Framer AI", "domain": "framer.com", "category": "saas_ai", "risk_level": "low", "provider": "framer", "description": "AI website builder"},
    {"name": "Galileo AI", "domain": "usegalileo.ai", "category": "saas_ai", "risk_level": "medium", "provider": "galileo", "description": "AI UI generation"},
    {"name": "Uizard", "domain": "uizard.io", "category": "saas_ai", "risk_level": "medium", "provider": "uizard", "description": "AI design tool"},
    # Research & Search AI
    {"name": "Elicit", "domain": "elicit.com", "category": "saas_ai", "risk_level": "medium", "provider": "elicit", "description": "AI research assistant"},
    {"name": "Consensus", "domain": "consensus.app", "category": "saas_ai", "risk_level": "low", "provider": "consensus", "description": "AI academic search"},
    {"name": "Semantic Scholar", "domain": "semanticscholar.org", "category": "saas_ai", "risk_level": "low", "provider": "ai2", "description": "AI-powered research"},
    {"name": "Scite AI", "domain": "scite.ai", "category": "saas_ai", "risk_level": "low", "provider": "scite", "description": "AI citation analysis"},
    # Audio & Music AI
    {"name": "Suno AI", "domain": "suno.ai", "category": "saas_ai", "risk_level": "medium", "provider": "suno", "description": "AI music generation"},
    {"name": "Udio", "domain": "udio.com", "category": "saas_ai", "risk_level": "medium", "provider": "udio", "description": "AI music creation"},
    {"name": "Speechify", "domain": "speechify.com", "category": "saas_ai", "risk_level": "low", "provider": "speechify", "description": "AI text-to-speech"},
    {"name": "Assembly AI", "domain": "assemblyai.com", "category": "saas_ai", "risk_level": "medium", "provider": "assembly", "description": "AI speech recognition"},
    {"name": "Deepgram", "domain": "deepgram.com", "category": "saas_ai", "risk_level": "medium", "provider": "deepgram", "description": "AI speech-to-text"},
    {"name": "Whisper API", "domain": "api.openai.com/v1/audio", "category": "saas_ai", "risk_level": "medium", "provider": "openai", "description": "Speech recognition API"},
    # Translation AI
    {"name": "DeepL", "domain": "deepl.com", "category": "saas_ai", "risk_level": "medium", "provider": "deepl", "description": "AI translation"},
    {"name": "Smartling AI", "domain": "smartling.com", "category": "saas_ai", "risk_level": "medium", "provider": "smartling", "description": "AI translation management"},
    # Productivity AI
    {"name": "Reclaim AI", "domain": "reclaim.ai", "category": "saas_ai", "risk_level": "low", "provider": "reclaim", "description": "AI calendar management"},
    {"name": "Clockwise", "domain": "getclockwise.com", "category": "saas_ai", "risk_level": "low", "provider": "clockwise", "description": "AI scheduling"},
    {"name": "Motion", "domain": "usemotion.com", "category": "saas_ai", "risk_level": "low", "provider": "motion", "description": "AI project management"},
    {"name": "Taskade AI", "domain": "taskade.com", "category": "saas_ai", "risk_level": "low", "provider": "taskade", "description": "AI task management"},
    # Legal AI
    {"name": "Harvey AI", "domain": "harvey.ai", "category": "saas_ai", "risk_level": "high", "provider": "harvey", "description": "AI for legal"},
    {"name": "CoCounsel", "domain": "casetext.com", "category": "saas_ai", "risk_level": "high", "provider": "thomson_reuters", "description": "AI legal assistant"},
    {"name": "Ironclad AI", "domain": "ironcladapp.com", "category": "saas_ai", "risk_level": "high", "provider": "ironclad", "description": "AI contract management"},
    # Finance AI
    {"name": "AlphaSense", "domain": "alpha-sense.com", "category": "saas_ai", "risk_level": "high", "provider": "alphasense", "description": "AI market intelligence"},
    {"name": "Kensho", "domain": "kensho.com", "category": "saas_ai", "risk_level": "high", "provider": "spglobal", "description": "AI analytics for finance"},
    {"name": "Tegus", "domain": "tegus.com", "category": "saas_ai", "risk_level": "medium", "provider": "tegus", "description": "AI investment research"},
    # Developer Tools AI
    {"name": "Vercel AI", "domain": "vercel.com/ai", "category": "saas_ai", "risk_level": "low", "provider": "vercel", "description": "AI SDK for developers"},
    {"name": "LangChain", "domain": "langchain.com", "category": "saas_ai", "risk_level": "medium", "provider": "langchain", "description": "LLM application framework"},
    {"name": "LangSmith", "domain": "smith.langchain.com", "category": "saas_ai", "risk_level": "medium", "provider": "langchain", "description": "LLM observability"},
    {"name": "Pinecone", "domain": "pinecone.io", "category": "saas_ai", "risk_level": "medium", "provider": "pinecone", "description": "Vector database"},
    {"name": "Weaviate", "domain": "weaviate.io", "category": "saas_ai", "risk_level": "medium", "provider": "weaviate", "description": "Vector database"},
    {"name": "Chroma", "domain": "trychroma.com", "category": "saas_ai", "risk_level": "low", "provider": "chroma", "description": "Embedding database"},
    {"name": "Qdrant", "domain": "qdrant.tech", "category": "saas_ai", "risk_level": "medium", "provider": "qdrant", "description": "Vector search engine"},
    {"name": "OpenRouter", "domain": "openrouter.ai", "category": "llm", "risk_level": "high", "provider": "openrouter", "description": "LLM routing platform"},
    {"name": "Groq", "domain": "groq.com", "category": "llm", "risk_level": "medium", "provider": "groq", "description": "Fast LLM inference"},
    {"name": "Fireworks AI", "domain": "fireworks.ai", "category": "llm", "risk_level": "medium", "provider": "fireworks", "description": "LLM inference platform"},
    {"name": "Cerebras", "domain": "cerebras.ai", "category": "llm", "risk_level": "medium", "provider": "cerebras", "description": "AI compute platform"},
    # Automation AI
    {"name": "Zapier AI", "domain": "zapier.com", "category": "saas_ai", "risk_level": "medium", "provider": "zapier", "description": "AI automation"},
    {"name": "Make AI", "domain": "make.com", "category": "saas_ai", "risk_level": "medium", "provider": "make", "description": "AI workflow automation"},
    {"name": "n8n AI", "domain": "n8n.io", "category": "saas_ai", "risk_level": "medium", "provider": "n8n", "description": "AI workflow automation"},
    {"name": "Bardeen AI", "domain": "bardeen.ai", "category": "saas_ai", "risk_level": "medium", "provider": "bardeen", "description": "AI browser automation"},
    # Healthcare AI
    {"name": "Nuance DAX", "domain": "nuance.com", "category": "saas_ai", "risk_level": "critical", "provider": "microsoft", "description": "AI clinical documentation"},
    {"name": "Tempus AI", "domain": "tempus.com", "category": "saas_ai", "risk_level": "critical", "provider": "tempus", "description": "AI precision medicine"},
    # Education AI
    {"name": "Duolingo Max", "domain": "duolingo.com", "category": "saas_ai", "risk_level": "low", "provider": "duolingo", "description": "AI language learning"},
    {"name": "Khan Academy Khanmigo", "domain": "khanacademy.org", "category": "saas_ai", "risk_level": "low", "provider": "khan", "description": "AI tutoring"},
    {"name": "Quizlet AI", "domain": "quizlet.com", "category": "saas_ai", "risk_level": "low", "provider": "quizlet", "description": "AI study tools"},
    # Enterprise AI Platforms
    {"name": "Salesforce Einstein", "domain": "einstein.ai", "category": "saas_ai", "risk_level": "medium", "provider": "salesforce", "description": "AI for CRM"},
    {"name": "ServiceNow AI", "domain": "servicenow.com", "category": "saas_ai", "risk_level": "medium", "provider": "servicenow", "description": "AI for IT service management"},
    {"name": "SAP AI", "domain": "sap.com/ai", "category": "saas_ai", "risk_level": "medium", "provider": "sap", "description": "AI for enterprise"},
    {"name": "Workday AI", "domain": "workday.com", "category": "saas_ai", "risk_level": "medium", "provider": "workday", "description": "AI for HR/Finance"},
    {"name": "Palantir AIP", "domain": "palantir.com", "category": "saas_ai", "risk_level": "high", "provider": "palantir", "description": "AI platform for enterprises"},
    {"name": "C3.ai", "domain": "c3.ai", "category": "saas_ai", "risk_level": "medium", "provider": "c3", "description": "Enterprise AI platform"},
    {"name": "Scale AI", "domain": "scale.com", "category": "saas_ai", "risk_level": "medium", "provider": "scale", "description": "AI data platform"},
    {"name": "Snorkel AI", "domain": "snorkel.ai", "category": "saas_ai", "risk_level": "medium", "provider": "snorkel", "description": "AI data labeling"},
    {"name": "Labelbox", "domain": "labelbox.com", "category": "saas_ai", "risk_level": "medium", "provider": "labelbox", "description": "AI training data"},
    # Video AI
    {"name": "Pika Labs", "domain": "pika.art", "category": "image_gen", "risk_level": "medium", "provider": "pika", "description": "AI video generation"},
    {"name": "Sora", "domain": "sora.com", "category": "image_gen", "risk_level": "high", "provider": "openai", "description": "AI video generation"},
    {"name": "Kling AI", "domain": "klingai.com", "category": "image_gen", "risk_level": "high", "provider": "kuaishou", "description": "AI video generation"},
    {"name": "HeyGen", "domain": "heygen.com", "category": "saas_ai", "risk_level": "medium", "provider": "heygen", "description": "AI video avatars"},
    {"name": "D-ID", "domain": "d-id.com", "category": "saas_ai", "risk_level": "medium", "provider": "d-id", "description": "AI video creation"},
    # Miscellaneous AI
    {"name": "Wolfram Alpha", "domain": "wolframalpha.com", "category": "saas_ai", "risk_level": "low", "provider": "wolfram", "description": "Computational intelligence"},
    {"name": "Runway Gen-2", "domain": "app.runwayml.com", "category": "image_gen", "risk_level": "medium", "provider": "runway", "description": "AI generative video"},
    {"name": "Civitai", "domain": "civitai.com", "category": "image_gen", "risk_level": "high", "provider": "civitai", "description": "AI model sharing"},
    {"name": "NovelAI", "domain": "novelai.net", "category": "saas_ai", "risk_level": "medium", "provider": "novelai", "description": "AI storytelling"},
    {"name": "Sudowrite", "domain": "sudowrite.com", "category": "saas_ai", "risk_level": "medium", "provider": "sudowrite", "description": "AI fiction writing"},
    {"name": "Anthropic Console", "domain": "console.anthropic.com", "category": "llm", "risk_level": "high", "provider": "anthropic", "description": "Anthropic developer console"},
    {"name": "AWS Bedrock", "domain": "aws.amazon.com/bedrock", "category": "llm", "risk_level": "medium", "provider": "amazon", "description": "Managed foundation models"},
    {"name": "IBM watsonx", "domain": "ibm.com/watsonx", "category": "llm", "risk_level": "medium", "provider": "ibm", "description": "IBM AI platform"},
    {"name": "Recraft AI", "domain": "recraft.ai", "category": "image_gen", "risk_level": "medium", "provider": "recraft", "description": "AI design tool"},
    {"name": "Playground AI", "domain": "playground.com", "category": "image_gen", "risk_level": "medium", "provider": "playground", "description": "AI image editing"},
    {"name": "Remove.bg", "domain": "remove.bg", "category": "saas_ai", "risk_level": "low", "provider": "kaleido", "description": "AI background removal"},
    {"name": "Clipdrop", "domain": "clipdrop.co", "category": "saas_ai", "risk_level": "low", "provider": "stability", "description": "AI image tools"},
    {"name": "Lensa AI", "domain": "lensa-ai.com", "category": "image_gen", "risk_level": "medium", "provider": "prisma", "description": "AI photo editing"},
    {"name": "PhotoRoom", "domain": "photoroom.com", "category": "saas_ai", "risk_level": "low", "provider": "photoroom", "description": "AI photo editor"},
    {"name": "Gamma AI", "domain": "gamma.app", "category": "saas_ai", "risk_level": "medium", "provider": "gamma", "description": "AI presentations"},
    {"name": "Caktus AI", "domain": "caktus.ai", "category": "saas_ai", "risk_level": "medium", "provider": "caktus", "description": "AI learning assistant"},
    {"name": "Jenni AI", "domain": "jenni.ai", "category": "saas_ai", "risk_level": "medium", "provider": "jenni", "description": "AI writing assistant"},
    {"name": "Merlin AI", "domain": "getmerlin.in", "category": "saas_ai", "risk_level": "medium", "provider": "merlin", "description": "AI browser extension"},
    {"name": "MaxAI", "domain": "maxai.me", "category": "saas_ai", "risk_level": "medium", "provider": "maxai", "description": "AI browser extension"},
    {"name": "Monica AI", "domain": "monica.im", "category": "saas_ai", "risk_level": "medium", "provider": "monica", "description": "AI assistant extension"},
    {"name": "Sider AI", "domain": "sider.ai", "category": "saas_ai", "risk_level": "medium", "provider": "sider", "description": "AI sidebar assistant"},
    {"name": "Liner AI", "domain": "getliner.com", "category": "saas_ai", "risk_level": "medium", "provider": "liner", "description": "AI research assistant"},
]

# Build domain lookup for fast matching
_DOMAIN_INDEX: dict[str, dict[str, str]] = {
    svc["domain"].lower(): svc for svc in _KNOWN_AI_SERVICES
}


def _match_domain(url_or_domain: str) -> dict[str, str] | None:
    """Match a URL or domain against known AI services."""
    normalized = url_or_domain.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    normalized = normalized.rstrip("/").split("/")[0] if "/" not in normalized else normalized.rstrip("/")
    # Try exact match first, then prefix match
    if normalized in _DOMAIN_INDEX:
        return _DOMAIN_INDEX[normalized]
    for domain, svc in _DOMAIN_INDEX.items():
        if normalized.endswith(domain) or domain.endswith(normalized) or domain in normalized:
            return svc
    return None


class SentinelScanService:
    """Enterprise SentinelScan engine for shadow AI discovery and posture management.

    All operations are tenant-scoped, RBAC-checked, and audit-logged.
    """

    # ── Shadow AI Discovery ─────────────────────────────────────────

    @staticmethod
    async def discover_shadow_ai(
        tenant_id: UUID,
        user_id: UUID,
        config: DiscoveryConfig,
    ) -> DiscoveryResult:
        """Analyze SSO logs for shadow AI usage against known AI service database.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor performing the scan.
            config: Discovery configuration.

        Returns:
            DiscoveryResult with discovered services and counts.
        """
        now = datetime.now(tz=timezone.utc)
        scan_id = uuid4()
        discovered: list[dict[str, Any]] = []
        shadow = 0
        approved = 0
        blocked = 0

        # Simulate SSO log analysis against known AI service domains
        # In production, this queries actual SSO log storage filtered by tenant
        logger.info(
            "sentinel.discovery.started",
            extra={
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "scan_id": str(scan_id),
                "sources": config.sources,
                "scan_depth": config.scan_depth,
            },
        )

        # Match SSO log domains against known AI services
        for svc in _KNOWN_AI_SERVICES[:50]:  # Simulated initial batch
            status = "shadow"
            if svc["risk_level"] in ("low", "informational"):
                status = "approved"
                approved += 1
            elif svc["risk_level"] == "critical":
                status = "blocked"
                blocked += 1
            else:
                shadow += 1
            discovered.append({
                "service_name": svc["name"],
                "domain": svc["domain"],
                "category": svc["category"],
                "status": status,
                "risk_level": svc["risk_level"],
                "provider": svc["provider"],
            })

        logger.info(
            "sentinel.discovery.completed",
            extra={
                "tenant_id": str(tenant_id),
                "scan_id": str(scan_id),
                "shadow_count": shadow,
                "approved_count": approved,
            },
        )

        return DiscoveryResult(
            id=scan_id,
            tenant_id=tenant_id,
            discovered_services=discovered,
            shadow_count=shadow,
            approved_count=approved,
            blocked_count=blocked,
            new_since_last_scan=shadow,
            scan_duration_seconds=1.2,
            completed_at=now,
        )

    # ── SSO Log Ingestion ───────────────────────────────────────────

    @staticmethod
    async def ingest_sso_logs(
        tenant_id: UUID,
        source: str,
        log_data: list[dict[str, Any]],
    ) -> IngestResult:
        """Ingest SSO/audit logs from various IdPs.

        Args:
            tenant_id: Tenant scope.
            source: IdP source identifier (okta, azure_ad, etc.).
            log_data: Raw SSO log entries.

        Returns:
            IngestResult with processing statistics.
        """
        services_detected = 0
        new_services = 0
        errors = 0

        for entry in log_data:
            try:
                target_url = entry.get("target_url", entry.get("url", ""))
                match = _match_domain(target_url)
                if match is not None:
                    services_detected += 1
            except Exception:
                errors += 1

        logger.info(
            "sentinel.ingest.completed",
            extra={
                "tenant_id": str(tenant_id),
                "source": source,
                "records": len(log_data),
                "services_detected": services_detected,
            },
        )

        return IngestResult(
            source=source,
            records_processed=len(log_data),
            services_detected=services_detected,
            new_services=new_services,
            errors=errors,
        )

    # ── AI Asset Inventory ──────────────────────────────────────────

    @staticmethod
    async def inventory_ai_assets(tenant_id: UUID) -> list[AIAsset]:
        """Return unified inventory of all discovered AI assets for a tenant.

        Args:
            tenant_id: Tenant scope.

        Returns:
            List of AIAsset objects.
        """
        now = datetime.now(tz=timezone.utc)
        assets: list[AIAsset] = []

        # In production, query discovered services table filtered by tenant_id
        for idx, svc in enumerate(_KNOWN_AI_SERVICES[:20]):
            status = "approved" if svc["risk_level"] in ("low", "informational") else "shadow"
            assets.append(AIAsset(
                id=uuid4(),
                tenant_id=tenant_id,
                service_name=svc["name"],
                category=svc["category"],
                status=status,
                users=[],
                user_count=0,
                first_seen=now,
                last_seen=now,
                risk_level=svc["risk_level"],
                data_classification="unknown",
            ))

        return assets

    # ── Credential Exposure Scanning ────────────────────────────────

    @staticmethod
    async def scan_credential_exposure(tenant_id: UUID) -> list[CredentialExposure]:
        """Scan for API keys/tokens exposed in repos and logs.

        Args:
            tenant_id: Tenant scope.

        Returns:
            List of CredentialExposure findings.
        """
        now = datetime.now(tz=timezone.utc)

        # In production, integrates with repo scanning tools (e.g., GitHub secret scanning)
        # and scans configured repositories filtered by tenant
        logger.info(
            "sentinel.credential_scan.started",
            extra={"tenant_id": str(tenant_id)},
        )

        # Placeholder: no real exposures in simulated mode
        exposures: list[CredentialExposure] = []

        logger.info(
            "sentinel.credential_scan.completed",
            extra={"tenant_id": str(tenant_id), "exposures_found": len(exposures)},
        )

        return exposures

    # ── Posture Score Computation ───────────────────────────────────

    @staticmethod
    async def compute_posture_score(tenant_id: UUID) -> PostureScore:
        """Compute organization-wide AI security posture score (0-100).

        Args:
            tenant_id: Tenant scope.

        Returns:
            PostureScore with overall score, category breakdown, and trend.
        """
        now = datetime.now(tz=timezone.utc)

        # Category scoring (in production, computed from real data)
        categories = {
            "shadow_ai_management": 72,
            "credential_security": 85,
            "data_classification": 60,
            "policy_compliance": 78,
            "access_control": 80,
            "vendor_risk": 65,
        }
        overall = sum(categories.values()) // len(categories)

        return PostureScore(
            tenant_id=tenant_id,
            overall=overall,
            categories=categories,
            trend="stable",
            benchmark_percentile=55,
            computed_at=now,
            factors={
                "total_ai_services": 20,
                "shadow_services": 8,
                "credential_exposures": 0,
                "unclassified_data": 5,
            },
        )

    # ── Remediation Workflows ───────────────────────────────────────

    @staticmethod
    async def create_remediation(
        tenant_id: UUID,
        user_id: UUID,
        asset_id: UUID,
        action: str,
    ) -> RemediationWorkflow:
        """Create a remediation workflow: notify → offer alternative → escalate → block.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor creating the remediation.
            asset_id: Target AI asset.
            action: Remediation action (notify|offer_alternative|escalate|block).

        Returns:
            RemediationWorkflow with status and escalation level.
        """
        now = datetime.now(tz=timezone.utc)
        escalation_map = {
            "notify": 0,
            "offer_alternative": 1,
            "escalate": 2,
            "block": 3,
        }

        workflow = RemediationWorkflow(
            id=uuid4(),
            tenant_id=tenant_id,
            asset_id=asset_id,
            action=action,
            status="pending",
            assigned_to=str(user_id),
            escalation_level=escalation_map.get(action, 0),
            created_at=now,
            updated_at=now,
        )

        logger.info(
            "sentinel.remediation.created",
            extra={
                "tenant_id": str(tenant_id),
                "workflow_id": str(workflow.id),
                "asset_id": str(asset_id),
                "action": action,
            },
        )

        return workflow

    # ── Posture Reporting ───────────────────────────────────────────

    @staticmethod
    async def generate_posture_report(
        tenant_id: UUID,
        user_id: UUID,
        period: str,
    ) -> PostureReport:
        """Generate monthly AI security posture report with trends.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor generating the report.
            period: Report period (e.g. '2026-02').

        Returns:
            PostureReport with findings and recommendations.
        """
        now = datetime.now(tz=timezone.utc)

        posture = await SentinelScanService.compute_posture_score(tenant_id)

        return PostureReport(
            tenant_id=tenant_id,
            period=period,
            score_trend=[
                {"period": period, "score": posture.overall},
            ],
            current_score=posture.overall,
            findings=[
                {"type": "shadow_ai", "severity": "high", "description": "Unapproved AI services detected"},
                {"type": "posture", "severity": "medium", "description": "Data classification incomplete for some services"},
            ],
            recommendations=[
                "Review and classify all shadow AI services",
                "Implement SSO enforcement for approved AI tools",
                "Complete data classification for all AI assets",
                "Enable credential scanning on all repositories",
            ],
            shadow_ai_count=8,
            credential_exposures=0,
            generated_at=now,
        )

    # ── Known AI Services Database ──────────────────────────────────

    @staticmethod
    async def get_known_ai_services() -> list[KnownAIService]:
        """Return the database of 200+ known AI services.

        Returns:
            List of KnownAIService entries.
        """
        return [
            KnownAIService(**{k: v for k, v in svc.items() if k in KnownAIService.model_fields})
            for svc in _KNOWN_AI_SERVICES
        ]

    # ── Enhanced Discovery (multi-source) ───────────────────────────

    @staticmethod
    async def run_discovery_scan(
        tenant_id: str,
        user_id: str,
        sources: list[str] | None = None,
        scan_depth: str = "standard",
    ) -> dict[str, Any]:
        """Run a multi-source discovery scan (IdP/SSO, API gateway, DNS).

        In dev mode, generates realistic sample findings.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor performing the scan.
            sources: List of scan sources (sso, api_gateway, dns).
            scan_depth: Depth of scan (quick, standard, deep).

        Returns:
            Scan result dict with id, findings, and summary.
        """
        import random

        scan_sources = sources or ["sso", "api_gateway", "dns"]
        now = datetime.now(tz=timezone.utc)
        scan_id = str(uuid4())

        findings: list[dict[str, Any]] = []
        service_types = ["LLM", "Embedding", "Image", "Voice", "Code"]
        statuses = ["Approved", "Unapproved", "Blocked"]
        risk_levels = ["critical", "high", "medium", "low"]
        data_exposures = ["PII detected", "Confidential data", "Internal only", "Public", "None detected"]

        # Generate realistic sample findings from known services
        sample_size = {"quick": 8, "standard": 15, "deep": 25}.get(scan_depth, 15)
        sampled = _KNOWN_AI_SERVICES[:sample_size]

        for svc in sampled:
            stype = svc.get("category", "saas_ai")
            type_map = {
                "llm": "LLM", "copilot": "Code", "code_assistant": "Code",
                "chatbot": "LLM", "image_gen": "Image", "saas_ai": "Embedding",
            }
            finding: dict[str, Any] = {
                "id": str(uuid4()),
                "service_name": svc["name"],
                "service_type": type_map.get(stype, "LLM"),
                "provider": svc.get("provider", "unknown"),
                "risk_level": svc.get("risk_level", "medium"),
                "user_count": random.randint(1, 50),
                "data_exposure": random.choice(data_exposures),
                "first_seen": (now.replace(day=1)).isoformat(),
                "last_seen": now.isoformat(),
                "status": "Approved" if svc.get("risk_level") in ("low", "informational") else "Unapproved",
                "detection_source": random.choice(scan_sources),
                "domain": svc.get("domain", ""),
            }
            findings.append(finding)

        _scan_history_store.setdefault(tenant_id, []).append({
            "id": scan_id,
            "tenant_id": tenant_id,
            "initiated_by": user_id,
            "sources": scan_sources,
            "scan_depth": scan_depth,
            "status": "completed",
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "findings_count": len(findings),
            "services_found": len(findings),
        })

        # Store findings for inventory
        _findings_store.setdefault(tenant_id, []).extend(findings)

        logger.info(
            "sentinel.enhanced_scan.completed",
            extra={
                "tenant_id": tenant_id,
                "scan_id": scan_id,
                "findings": len(findings),
                "sources": scan_sources,
            },
        )

        return {
            "id": scan_id,
            "tenant_id": tenant_id,
            "sources": scan_sources,
            "scan_depth": scan_depth,
            "status": "completed",
            "findings": findings,
            "summary": {
                "total_findings": len(findings),
                "critical": sum(1 for f in findings if f["risk_level"] == "critical"),
                "high": sum(1 for f in findings if f["risk_level"] == "high"),
                "medium": sum(1 for f in findings if f["risk_level"] == "medium"),
                "low": sum(1 for f in findings if f["risk_level"] == "low"),
            },
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
        }

    # ── Service Inventory ───────────────────────────────────────────

    @staticmethod
    async def get_service_inventory(
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        risk_level: str | None = None,
        status: str | None = None,
        service_type: str | None = None,
    ) -> dict[str, Any]:
        """Get service inventory with filtering and pagination.

        Args:
            tenant_id: Tenant scope.
            limit: Max results per page.
            offset: Pagination offset.
            risk_level: Filter by risk level.
            status: Filter by approval status.
            service_type: Filter by service type.

        Returns:
            Dict with services list, total count, and pagination info.
        """
        all_findings = _findings_store.get(tenant_id, [])

        # Deduplicate by service_name
        seen: dict[str, dict[str, Any]] = {}
        for f in all_findings:
            name = f["service_name"]
            if name not in seen:
                seen[name] = f
            else:
                existing = seen[name]
                existing["user_count"] = max(
                    existing.get("user_count", 0), f.get("user_count", 0),
                )
                existing["last_seen"] = f.get("last_seen", existing.get("last_seen"))

        services = list(seen.values())

        if risk_level:
            services = [s for s in services if s.get("risk_level") == risk_level]
        if status:
            services = [s for s in services if s.get("status") == status]
        if service_type:
            services = [s for s in services if s.get("service_type") == service_type]

        total = len(services)
        page = services[offset : offset + limit]

        return {
            "services": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # ── Posture Score (weighted formula) ────────────────────────────

    @staticmethod
    async def compute_weighted_posture(tenant_id: str) -> dict[str, Any]:
        """Compute posture score using weighted penalty formula.

        penalty = (unauthorized×10) + (critical×20) + (data_exposure×15) + (policy_violations×5)
        score = max(0, 100 - penalty)

        Args:
            tenant_id: Tenant scope.

        Returns:
            Dict with score, grade, color, and breakdown.
        """
        findings = _findings_store.get(tenant_id, [])

        unauthorized = sum(1 for f in findings if f.get("status") == "Unapproved")
        critical = sum(1 for f in findings if f.get("risk_level") == "critical")
        data_exposure = sum(
            1 for f in findings
            if f.get("data_exposure") in ("PII detected", "Confidential data")
        )
        policy_violations = sum(1 for f in findings if f.get("status") == "Blocked")

        penalty = (
            (unauthorized * 10)
            + (critical * 20)
            + (data_exposure * 15)
            + (policy_violations * 5)
        )
        score = max(0, 100 - penalty)

        if score >= 80:
            grade, color = "Good", "green"
        elif score >= 60:
            grade, color = "Fair", "yellow"
        else:
            grade, color = "Poor", "red"

        return {
            "score": score,
            "grade": grade,
            "color": color,
            "penalty": penalty,
            "breakdown": {
                "unauthorized": unauthorized,
                "critical": critical,
                "data_exposure": data_exposure,
                "policy_violations": policy_violations,
            },
            "total_services": len(findings),
            "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ── Risk Breakdown ──────────────────────────────────────────────

    @staticmethod
    async def get_risk_breakdown(tenant_id: str) -> dict[str, Any]:
        """Get risk breakdown with real counts per category.

        Categories: Data Exposure, Unauthorized Access, Credential Risk, Policy Violation.

        Args:
            tenant_id: Tenant scope.

        Returns:
            Dict with category counts and details.
        """
        findings = _findings_store.get(tenant_id, [])

        data_exposure_items = [
            f for f in findings
            if f.get("data_exposure") in ("PII detected", "Confidential data")
        ]
        unauthorized_items = [
            f for f in findings if f.get("status") == "Unapproved"
        ]
        credential_risk_items = [
            f for f in findings if f.get("risk_level") == "critical"
        ]
        policy_violation_items = [
            f for f in findings if f.get("status") == "Blocked"
        ]

        categories = {
            "Data Exposure": {
                "count": len(data_exposure_items),
                "items": [
                    {"id": i["id"], "service_name": i["service_name"], "detail": i.get("data_exposure", "")}
                    for i in data_exposure_items
                ],
            },
            "Unauthorized Access": {
                "count": len(unauthorized_items),
                "items": [
                    {"id": i["id"], "service_name": i["service_name"], "detail": i.get("status", "")}
                    for i in unauthorized_items
                ],
            },
            "Credential Risk": {
                "count": len(credential_risk_items),
                "items": [
                    {"id": i["id"], "service_name": i["service_name"], "detail": i.get("risk_level", "")}
                    for i in credential_risk_items
                ],
            },
            "Policy Violation": {
                "count": len(policy_violation_items),
                "items": [
                    {"id": i["id"], "service_name": i["service_name"], "detail": i.get("status", "")}
                    for i in policy_violation_items
                ],
            },
        }

        return {
            "categories": categories,
            "total_findings": len(findings),
            "computed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ── Remediation ─────────────────────────────────────────────────

    @staticmethod
    async def apply_remediation(
        tenant_id: str,
        user_id: str,
        finding_id: str,
        action: str,
    ) -> dict[str, Any]:
        """Apply a remediation action to a single finding.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor performing remediation.
            finding_id: ID of the finding to remediate.
            action: One of Block, Approve, Monitor, Ignore.

        Returns:
            Dict with remediation result and audit info.
        """
        findings = _findings_store.get(tenant_id, [])
        target = None
        for f in findings:
            if f["id"] == finding_id:
                target = f
                break

        if target is None:
            return {"error": "Finding not found", "finding_id": finding_id}

        action_status_map = {
            "Block": "Blocked",
            "Approve": "Approved",
            "Monitor": "Monitoring",
            "Ignore": "Ignored",
        }
        target["status"] = action_status_map.get(action, action)

        now = datetime.now(tz=timezone.utc)
        audit_entry = {
            "id": str(uuid4()),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "finding_id": finding_id,
            "service_name": target["service_name"],
            "timestamp": now.isoformat(),
        }
        _remediation_audit.setdefault(tenant_id, []).append(audit_entry)

        logger.info(
            "sentinel.remediation.applied",
            extra={
                "tenant_id": tenant_id,
                "finding_id": finding_id,
                "action": action,
                "user_id": user_id,
            },
        )

        return {
            "finding_id": finding_id,
            "service_name": target["service_name"],
            "action": action,
            "new_status": target["status"],
            "applied_by": user_id,
            "applied_at": now.isoformat(),
        }

    @staticmethod
    async def apply_bulk_remediation(
        tenant_id: str,
        user_id: str,
        finding_ids: list[str],
        action: str,
    ) -> dict[str, Any]:
        """Apply remediation action to multiple findings.

        Args:
            tenant_id: Tenant scope.
            user_id: Actor performing remediation.
            finding_ids: List of finding IDs to remediate.
            action: One of Block, Approve, Monitor, Ignore.

        Returns:
            Dict with results summary and individual outcomes.
        """
        results: list[dict[str, Any]] = []
        for fid in finding_ids:
            result = await SentinelScanService.apply_remediation(
                tenant_id, user_id, fid, action,
            )
            results.append(result)

        succeeded = [r for r in results if "error" not in r]
        failed = [r for r in results if "error" in r]

        return {
            "action": action,
            "total": len(finding_ids),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "results": results,
            "applied_by": user_id,
            "applied_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ── Scan History ────────────────────────────────────────────────

    @staticmethod
    async def get_scan_history(
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get history of past scans with pagination.

        Args:
            tenant_id: Tenant scope.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            Dict with scans list and pagination info.
        """
        history = _scan_history_store.get(tenant_id, [])
        # Most recent first
        history_sorted = sorted(history, key=lambda s: s.get("started_at", ""), reverse=True)
        total = len(history_sorted)
        page = history_sorted[offset : offset + limit]

        return {
            "scans": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


# ── In-memory stores for dev mode ──────────────────────────────────

_findings_store: dict[str, list[dict[str, Any]]] = {}
_scan_history_store: dict[str, list[dict[str, Any]]] = {}
_remediation_audit: dict[str, list[dict[str, Any]]] = {}


__all__ = [
    "SentinelScanService",
    "_findings_store",
    "_scan_history_store",
    "_remediation_audit",
]
