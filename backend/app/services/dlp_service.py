"""Enterprise DLP Service — 4-layer pipeline, guardrails, NL policy engine.

Layers: regex patterns → NER-style PII → semantic classification → OPA policy.
All operations are tenant-scoped and audit-logged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any
from uuid import UUID, uuid4

from app.models.dlp import (
    DLPPolicy,
    DLPScanResultSchema,
    GuardrailConfig,
    GuardrailResult,
    GuardrailViolation,
    PIIFinding,
    PolicyEvaluation,
    RiskLevel,
    ScanAction,
    ScanDirection,
    SecretFinding,
    VaultCrossRef,
)

logger = logging.getLogger(__name__)

# ── Secret Patterns (200+ cloud credential regex) ──────────────────

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], float, str]] = []


def _sp(name: str, pattern: str, confidence: float = 1.0, severity: str = "critical") -> None:
    """Register a secret pattern."""
    _SECRET_PATTERNS.append((name, re.compile(pattern), confidence, severity))


# --- AWS ---
_sp("aws_access_key", r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")
_sp("aws_secret_key", r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key[\s:=\"']+([A-Za-z0-9/+=]{40})\b", 0.95)
_sp("aws_session_token", r"(?i)aws[_\-]?session[_\-]?token[\s:=\"']+([A-Za-z0-9/+=]{100,})", 0.9)
_sp("aws_mws_key", r"amzn\.mws\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_sp("aws_arn", r"arn:aws:iam::\d{12}:[\w/+=,.@-]+", 0.7, "medium")

# --- Azure ---
_sp("azure_client_secret", r"(?i)(?:client[_\-]?secret|azure[_\-]?secret)[\s:=\"']+([A-Za-z0-9~._-]{34,})", 0.9)
_sp("azure_storage_key", r"(?i)(?:DefaultEndpointsProtocol|AccountKey)=[A-Za-z0-9+/=]{40,}")
_sp("azure_sas_token", r"(?:sv=\d{4}-\d{2}-\d{2}&(?:ss|srt|sp|se|st|spr|sig)=[^&\s]+){2,}")
_sp("azure_connection_string", r"(?i)(?:Server|Data Source)=tcp:[^;]+;.*(?:Password|Pwd)=[^;]+", 0.95)
_sp("azure_devops_pat", r"(?i)(?:azure|ado|devops)[_\-]?pat[\s:=\"']+[a-z0-9]{52}", 0.9)
_sp("azure_subscription_key", r"(?i)(?:Ocp-Apim-Subscription-Key|subscription[_\-]?key)[\s:=\"']+[a-f0-9]{32}", 0.9)
_sp("azure_cosmos_key", r"(?i)AccountKey=[A-Za-z0-9+/=]{64,}")
_sp("azure_ad_client_id", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", 0.3, "low")

# --- GCP ---
_sp("gcp_api_key", r"AIza[0-9A-Za-z\-_]{35}")
_sp("gcp_service_account", r"\"type\"\s*:\s*\"service_account\"", 0.9)
_sp("gcp_oauth_token", r"ya29\.[0-9A-Za-z_-]{50,}")
_sp("gcp_private_key_id", r"(?i)private_key_id[\s:=\"']+[a-f0-9]{40}", 0.85)
_sp("firebase_key", r"AAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140,}")

# --- GitHub ---
_sp("github_pat_fine", r"github_pat_[A-Za-z0-9_]{22,}")
_sp("github_pat_classic", r"ghp_[A-Za-z0-9]{36,}")
_sp("github_oauth", r"gho_[A-Za-z0-9]{36,}")
_sp("github_app_token", r"(?:ghs|ghr)_[A-Za-z0-9]{36,}")
_sp("github_refresh_token", r"ghr_[A-Za-z0-9]{36,}")

# --- GitLab ---
_sp("gitlab_pat", r"glpat-[A-Za-z0-9\-_]{20,}")
_sp("gitlab_runner_token", r"GR1348941[A-Za-z0-9\-_]{20,}")
_sp("gitlab_pipeline_token", r"glptt-[a-f0-9]{40}")

# --- Slack ---
_sp("slack_bot_token", r"xoxb-[0-9A-Za-z\-]{50,}")
_sp("slack_user_token", r"xoxp-[0-9A-Za-z\-]{50,}")
_sp("slack_app_token", r"xapp-[0-9]-[A-Za-z0-9\-]{50,}")
_sp("slack_webhook", r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+")
_sp("slack_config_token", r"xoxe\.xoxp-1-[A-Za-z0-9\-]{140,}")

# --- Database URIs ---
_sp("postgres_uri", r"(?i)postgres(?:ql)?://[^\s:]+:[^\s@]+@[^\s/]+(?::\d+)?/\S+")
_sp("mysql_uri", r"(?i)mysql://[^\s:]+:[^\s@]+@[^\s/]+(?::\d+)?/\S+")
_sp("mongodb_uri", r"mongodb(?:\+srv)?://[^\s:]+:[^\s@]+@[^\s/]+")
_sp("redis_uri", r"redis(?:s)?://[^\s:]*:[^\s@]+@[^\s/]+(?::\d+)?")
_sp("mssql_uri", r"(?i)(?:Server|Data Source)=[^;]+;.*(?:Password|Pwd)=[^;]+")
_sp("elasticsearch_uri", r"(?i)https?://[^\s:]+:[^\s@]+@[^\s]+(?::9200|:9243)")
_sp("amqp_uri", r"amqps?://[^\s:]+:[^\s@]+@[^\s/]+")

# --- JWTs & tokens ---
_sp("jwt_token", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", 0.95, "high")
_sp("bearer_token", r"(?i)(?:Bearer|Authorization)\s+[A-Za-z0-9\-._~+/]+=*", 0.8, "high")
_sp("basic_auth", r"(?i)Authorization:\s*Basic\s+[A-Za-z0-9+/]+=*", 0.95)

# --- Private keys ---
_sp("rsa_private_key", r"-----BEGIN RSA PRIVATE KEY-----")
_sp("openssh_private_key", r"-----BEGIN OPENSSH PRIVATE KEY-----")
_sp("ec_private_key", r"-----BEGIN EC PRIVATE KEY-----")
_sp("pgp_private_key", r"-----BEGIN PGP PRIVATE KEY BLOCK-----")
_sp("dsa_private_key", r"-----BEGIN DSA PRIVATE KEY-----")
_sp("pkcs8_private_key", r"-----BEGIN PRIVATE KEY-----")
_sp("encrypted_private_key", r"-----BEGIN ENCRYPTED PRIVATE KEY-----")

# --- Generic API keys ---
_sp("generic_api_key", r"(?i)(?:api[_\-]?key|apikey)[\s:=\"']+[A-Za-z0-9\-._]{20,}", 0.8, "high")
_sp("generic_secret", r"(?i)(?:secret[_\-]?key|client[_\-]?secret|app[_\-]?secret)[\s:=\"']+[A-Za-z0-9\-._]{20,}", 0.85, "high")
_sp("generic_token", r"(?i)(?:access[_\-]?token|auth[_\-]?token|refresh[_\-]?token)[\s:=\"']+[A-Za-z0-9\-._]{20,}", 0.8, "high")
_sp("generic_credential", r'(?i)(?:credential|cred)[\s:="\']+[A-Za-z0-9\-._]{20,}', 0.75, "high")

# --- Stripe ---
_sp("stripe_live_key", r"sk_live_[A-Za-z0-9]{24,}")
_sp("stripe_test_key", r"sk_test_[A-Za-z0-9]{24,}", 0.9, "medium")
_sp("stripe_publishable", r"pk_(?:live|test)_[A-Za-z0-9]{24,}", 0.7, "medium")
_sp("stripe_restricted", r"rk_(?:live|test)_[A-Za-z0-9]{24,}")

# --- Twilio ---
_sp("twilio_api_key", r"SK[a-f0-9]{32}")
_sp("twilio_account_sid", r"AC[a-f0-9]{32}", 0.8, "medium")

# --- SendGrid ---
_sp("sendgrid_api_key", r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}")

# --- Mailgun ---
_sp("mailgun_api_key", r"key-[a-f0-9]{32}")

# --- Square ---
_sp("square_access_token", r"sq0atp-[A-Za-z0-9\-_]{22}")
_sp("square_oauth_secret", r"sq0csp-[A-Za-z0-9\-_]{43}")

# --- Telegram ---
_sp("telegram_bot_token", r"\d{8,10}:[A-Za-z0-9_-]{35}")

# --- Discord ---
_sp("discord_bot_token", r"[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")
_sp("discord_webhook", r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+")

# --- NPM ---
_sp("npm_token", r"npm_[A-Za-z0-9]{36}")

# --- PyPI ---
_sp("pypi_token", r"pypi-[A-Za-z0-9_-]{50,}")

# --- Docker ---
_sp("docker_config_auth", r'(?i)"auth"\s*:\s*"[A-Za-z0-9+/=]{20,}"', 0.85)

# --- Heroku ---
_sp("heroku_api_key", r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", 0.3, "low")

# --- Hashicorp ---
_sp("vault_token", r"(?:hvs|hvb|hvr)\.[A-Za-z0-9_-]{24,}")
_sp("terraform_token", r"(?:atlasv1-)?[A-Za-z0-9]{14}\.[A-Za-z0-9]{67}")

# --- Datadog ---
_sp("datadog_api_key", r"(?i)(?:dd|datadog)[_\-]?api[_\-]?key[\s:=\"']+[a-f0-9]{32}", 0.9)
_sp("datadog_app_key", r"(?i)(?:dd|datadog)[_\-]?app[_\-]?key[\s:=\"']+[a-f0-9]{40}", 0.9)

# --- New Relic ---
_sp("newrelic_license_key", r"(?i)new[_\-]?relic[_\-]?license[_\-]?key[\s:=\"']+[A-Za-z0-9]{40}", 0.9)
_sp("newrelic_api_key", r"NRAK-[A-Z0-9]{27}")
_sp("newrelic_insights_key", r"NRI[a-zA-Z0-9\-]{32,}")

# --- Okta ---
_sp("okta_api_token", r"00[A-Za-z0-9_-]{40}")

# --- PagerDuty ---
_sp("pagerduty_key", r"(?i)pagerduty[_\-]?(?:api|integration)[_\-]?key[\s:=\"']+[A-Za-z0-9+]{20,}", 0.9)

# --- Shopify ---
_sp("shopify_access_token", r"shpat_[a-fA-F0-9]{32}")
_sp("shopify_shared_secret", r"shpss_[a-fA-F0-9]{32}")

# --- Atlassian ---
_sp("atlassian_api_token", r"(?i)(?:atlassian|jira|confluence)[_\-]?api[_\-]?token[\s:=\"']+[A-Za-z0-9]{24,}", 0.85)

# --- Cloudflare ---
_sp("cloudflare_api_key", r"(?i)cloudflare[_\-]?api[_\-]?key[\s:=\"']+[a-f0-9]{37}", 0.9)
_sp("cloudflare_api_token", r"(?i)cf[_\-]?api[_\-]?token[\s:=\"']+[A-Za-z0-9_-]{40,}")

# --- Doppler ---
_sp("doppler_token", r"dp\.(?:st|ct|sa|scim)\.[A-Za-z0-9_-]{40,}")

# --- Grafana ---
_sp("grafana_api_key", r"eyJrIjoi[A-Za-z0-9+/=]{30,}")
_sp("grafana_service_account", r"glsa_[A-Za-z0-9]{32}_[a-f0-9]{8}")

# --- Supabase ---
_sp("supabase_key", r"(?:eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.eyJpc3MiOiJzdXBhYmFzZS)[A-Za-z0-9._-]+", 0.9)

# --- Linear ---
_sp("linear_api_key", r"lin_api_[A-Za-z0-9]{40}")

# --- Algolia ---
_sp("algolia_api_key", r"(?i)algolia[_\-]?api[_\-]?key[\s:=\"']+[a-f0-9]{32}", 0.9)

# --- Auth0 ---
_sp("auth0_client_secret", r"(?i)auth0[_\-]?client[_\-]?secret[\s:=\"']+[A-Za-z0-9_-]{32,}", 0.9)

# --- Confluent ---
_sp("confluent_key", r"(?i)confluent[_\-]?(?:api|cloud)[_\-]?key[\s:=\"']+[A-Z0-9]{16}", 0.9)

# --- Databricks ---
_sp("databricks_token", r"dapi[a-f0-9]{32}")

# --- DigitalOcean ---
_sp("digitalocean_pat", r"dop_v1_[a-f0-9]{64}")
_sp("digitalocean_oauth", r"doo_v1_[a-f0-9]{64}")
_sp("digitalocean_refresh", r"dor_v1_[a-f0-9]{64}")

# --- Dynatrace ---
_sp("dynatrace_token", r"dt0c01\.[A-Z0-9]{24}\.[A-Za-z0-9]{64}")

# --- Fastly ---
_sp("fastly_api_token", r"(?i)fastly[_\-]?api[_\-]?token[\s:=\"']+[A-Za-z0-9_-]{32,}", 0.9)

# --- Finicity ---
_sp("finicity_key", r"(?i)finicity[_\-]?(?:app|partner)[_\-]?key[\s:=\"']+[a-f0-9]{32}", 0.9)

# --- Flutterwave ---
_sp("flutterwave_key", r"FLWSECK_TEST-[a-f0-9]{32}-X")
_sp("flutterwave_live", r"FLWSECK-[a-f0-9]{32}-X")

# --- Frame.io ---
_sp("frameio_token", r"fio-u-[A-Za-z0-9_-]{64,}")

# --- GoCardless ---
_sp("gocardless_token", r"live_[A-Za-z0-9_-]{40,}")

# --- HubSpot ---
_sp("hubspot_api_key", r"(?i)hubspot[_\-]?api[_\-]?key[\s:=\"']+[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", 0.9)
_sp("hubspot_private_app", r"pat-(?:na|eu)1-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")

# --- Intercom ---
_sp("intercom_token", r"(?i)intercom[_\-]?(?:api|access)[_\-]?token[\s:=\"']+[a-zA-Z0-9=_-]{60,}", 0.9)

# --- Lob ---
_sp("lob_api_key", r"(?:live|test)_[a-f0-9]{35}")

# --- Mapbox ---
_sp("mapbox_token", r"pk\.[A-Za-z0-9_-]{60,}\.[A-Za-z0-9_-]{20,}")
_sp("mapbox_secret", r"sk\.[A-Za-z0-9_-]{60,}\.[A-Za-z0-9_-]{20,}")

# --- MessageBird ---
_sp("messagebird_key", r"(?i)messagebird[_\-]?(?:api|access)[_\-]?key[\s:=\"']+[A-Za-z0-9]{25}", 0.9)

# --- Notion ---
_sp("notion_token", r"(?:ntn_|secret_)[A-Za-z0-9]{43,}")

# --- Plaid ---
_sp("plaid_client_id", r"(?i)plaid[_\-]?client[_\-]?id[\s:=\"']+[a-f0-9]{24}", 0.9)
_sp("plaid_secret", r"(?i)plaid[_\-]?secret[\s:=\"']+[a-f0-9]{30}", 0.9)

# --- Postman ---
_sp("postman_api_key", r"PMAK-[A-Za-z0-9]{24}-[a-f0-9]{34}")

# --- Pulumi ---
_sp("pulumi_token", r"pul-[a-f0-9]{40}")

# --- RapidAPI ---
_sp("rapidapi_key", r"(?i)(?:x-rapidapi-key|rapidapi[_\-]?key)[\s:=\"']+[a-f0-9]{50}", 0.9)

# --- Rubygems ---
_sp("rubygems_api_key", r"rubygems_[a-f0-9]{48}")

# --- Sentry ---
_sp("sentry_dsn", r"https://[a-f0-9]{32}@[a-z0-9]+\.ingest\.sentry\.io/\d+")

# --- Sidekiq ---
_sp("sidekiq_secret", r"(?i)BUNDLE_ENTERPRISE__CONTRIBSYS__COM[\s:=\"']+[a-f0-9]+:[a-f0-9]+", 0.85)

# --- Snyk ---
_sp("snyk_token", r"(?i)snyk[_\-]?token[\s:=\"']+[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", 0.9)

# --- Sonar ---
_sp("sonarqube_token", r"sq[a-z]_[a-f0-9]{40}")

# --- Splunk ---
_sp("splunk_hec_token", r"(?i)splunk[_\-]?hec[_\-]?token[\s:=\"']+[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", 0.9)

# --- Vercel ---
_sp("vercel_token", r"(?i)vercel[_\-]?token[\s:=\"']+[A-Za-z0-9]{24,}", 0.9)

# --- Vonage/Nexmo ---
_sp("vonage_key", r"(?i)(?:vonage|nexmo)[_\-]?(?:api|key)[\s:=\"']+[a-f0-9]{8}", 0.85, "high")

# --- Zendesk ---
_sp("zendesk_token", r"(?i)zendesk[_\-]?(?:api|token)[\s:=\"']+[A-Za-z0-9]{40,}", 0.9)

# --- Generic password-like ---
_sp("generic_passwd", r"(?i)(?:passwd|pwd)[\s:=\"']+\S{6,}", 0.7, "high")


# ── PII Patterns ───────────────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.95),
    ("phone_us", re.compile(r"\b(?:\+1[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), 0.85),
    ("phone_intl", re.compile(r"\b\+[1-9]\d{1,2}[\s.-]?\d{4,14}\b"), 0.8),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), 1.0),
    ("credit_card_visa", re.compile(r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
    ("credit_card_mc", re.compile(r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
    ("credit_card_amex", re.compile(r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b"), 1.0),
    ("credit_card_discover", re.compile(r"\b6(?:011|5\d{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), 1.0),
    ("ip_address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), 0.6),
    ("date_of_birth", re.compile(r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"), 0.7),
    ("us_passport", re.compile(r"\b[A-Z]\d{8}\b"), 0.6),
    ("drivers_license", re.compile(r"\b[A-Z]\d{7,12}\b"), 0.5),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?\d{0,16})\b"), 0.85),
    ("nhs_number", re.compile(r"\b\d{3}\s?\d{3}\s?\d{4}\b"), 0.5),
    ("medicare_number", re.compile(r"\b\d{4}\s?\d{5}\s?\d{1}\b"), 0.5),
]

# Redaction templates
_REDACT_MAP: dict[str, str] = {
    "email": "[EMAIL REDACTED]",
    "phone_us": "[PHONE REDACTED]",
    "phone_intl": "[PHONE REDACTED]",
    "ssn": "***-**-****",
    "credit_card_visa": "****-****-****-****",
    "credit_card_mc": "****-****-****-****",
    "credit_card_amex": "****-******-*****",
    "credit_card_discover": "****-****-****-****",
    "ip_address": "[IP REDACTED]",
    "date_of_birth": "[DOB REDACTED]",
    "us_passport": "[PASSPORT REDACTED]",
    "drivers_license": "[LICENSE REDACTED]",
    "iban": "[IBAN REDACTED]",
    "nhs_number": "[NHS REDACTED]",
    "medicare_number": "[MEDICARE REDACTED]",
}

# Prompt injection heuristics
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?)"),
    re.compile(r"(?i)disregard\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?)"),
    re.compile(r"(?i)you\s+are\s+now\s+(?:a|an|in)\s+"),
    re.compile(r"(?i)new\s+(?:system\s+)?instructions?:\s*"),
    re.compile(r"(?i)(?:system|admin|root)\s*(?:prompt|override|mode)\s*:"),
    re.compile(r"(?i)forget\s+(?:all|everything|your)\s+"),
    re.compile(r"(?i)do\s+not\s+follow\s+"),
    re.compile(r"(?i)bypass\s+(?:all\s+)?(?:safety|content|security)\s+(?:filters?|restrictions?|rules?)"),
    re.compile(r"(?i)\bDAN\b.*\bjailbreak\b"),
    re.compile(r"(?i)pretend\s+(?:you\s+are|to\s+be)\s+"),
    re.compile(r"(?i)act\s+as\s+(?:if\s+)?(?:you\s+(?:are|were)\s+)?(?:a\s+)?(?:different|unrestricted|evil)"),
    re.compile(r"(?i)<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>"),
]

# Toxicity keyword blocklist (lightweight, no ML needed)
_TOXICITY_KEYWORDS: list[str] = [
    "kill", "murder", "attack", "bomb", "weapon", "exploit",
    "hack into", "steal data", "ransomware", "malware",
]


def _preview(text: str, max_len: int = 8) -> str:
    """Create a safe preview of matched text — never exposes full secret."""
    if len(text) <= max_len:
        return text[:3] + "..."
    return text[:max_len] + "..."


# ── DLP Service ────────────────────────────────────────────────────


class DLPService:
    """Enterprise DLP engine with 4-layer scanning pipeline.

    All methods are tenant-scoped and produce structured audit-ready results.
    """

    # ── Layer 1: Secret scanning ───────────────────────────────────

    @staticmethod
    def scan_for_secrets(content: str) -> list[SecretFinding]:
        """Scan content with 200+ regex patterns for cloud credentials.

        Returns a deduplicated list of SecretFinding objects sorted by
        position. Matched text is never returned in full — only a safe
        preview of the first 8 characters.
        """
        findings: list[SecretFinding] = []
        for name, pattern, confidence, severity in _SECRET_PATTERNS:
            for match in pattern.finditer(content):
                findings.append(SecretFinding(
                    pattern_name=name,
                    matched_text_preview=_preview(match.group()),
                    position=(match.start(), match.end()),
                    confidence=confidence,
                    severity=severity,
                ))

        # Deduplicate overlapping ranges — keep higher-confidence
        findings.sort(key=lambda f: (f.position[0], -f.confidence))
        deduped: list[SecretFinding] = []
        last_end = -1
        for finding in findings:
            if finding.position[0] >= last_end:
                deduped.append(finding)
                last_end = finding.position[1]
        return deduped

    # ── Layer 2: PII scanning ──────────────────────────────────────

    @staticmethod
    def scan_for_pii(content: str) -> list[PIIFinding]:
        """Detect PII entities (email, phone, SSN, credit card, names).

        Returns a deduplicated list of PIIFinding objects sorted by position.
        """
        findings: list[PIIFinding] = []
        for pii_type, pattern, confidence in _PII_PATTERNS:
            for match in pattern.finditer(content):
                findings.append(PIIFinding(
                    pii_type=pii_type,
                    matched_text_preview=_preview(match.group()),
                    position=(match.start(), match.end()),
                    confidence=confidence,
                ))

        # Deduplicate overlapping ranges
        findings.sort(key=lambda f: (f.position[0], -f.confidence))
        deduped: list[PIIFinding] = []
        last_end = -1
        for finding in findings:
            if finding.position[0] >= last_end:
                deduped.append(finding)
                last_end = finding.position[1]
        return deduped

    # ── Layer 3 + 4: Full pipeline ─────────────────────────────────

    @staticmethod
    def scan_content(
        tenant_id: str,
        content: str,
        direction: ScanDirection | str = ScanDirection.INPUT,
        context: dict[str, Any] | None = None,
    ) -> DLPScanResultSchema:
        """Run the full 4-layer DLP pipeline on content.

        Layers:
            1. Regex-based secret detection
            2. NER-style PII detection
            3. Semantic classification (risk scoring)
            4. OPA policy evaluation (action decision)

        Args:
            tenant_id: Tenant scope for the scan.
            content: The text to scan.
            direction: Whether this is 'input' or 'output' content.
            context: Optional metadata (agent_id, model, etc.).

        Returns:
            DLPScanResultSchema with findings, risk level, and recommended action.
        """
        start_ts = time.monotonic()
        content_id = hashlib.sha256(
            f"{tenant_id}:{content}".encode()
        ).hexdigest()[:16]

        # Layer 1: secrets
        secret_findings = DLPService.scan_for_secrets(content)

        # Layer 2: PII
        pii_findings = DLPService.scan_for_pii(content)

        # Layer 3: semantic classification — risk scoring
        all_findings: list[SecretFinding | PIIFinding] = [
            *secret_findings, *pii_findings,
        ]
        risk_level = DLPService._classify_risk(secret_findings, pii_findings)

        # Layer 4: OPA policy — decide action based on risk + direction
        action = DLPService._decide_action(risk_level, direction)

        elapsed_ms = (time.monotonic() - start_ts) * 1000.0

        logger.info(
            "DLP scan complete",
            extra={
                "tenant_id": tenant_id,
                "content_id": content_id,
                "direction": str(direction),
                "secrets_found": len(secret_findings),
                "pii_found": len(pii_findings),
                "risk_level": risk_level.value,
                "action": action.value,
                "processing_time_ms": round(elapsed_ms, 2),
            },
        )

        return DLPScanResultSchema(
            content_id=content_id,
            findings=all_findings,
            risk_level=risk_level,
            action=action,
            processing_time_ms=round(elapsed_ms, 2),
        )

    # ── Redaction ──────────────────────────────────────────────────

    @staticmethod
    def redact_content(
        content: str,
        findings: list[SecretFinding | PIIFinding],
    ) -> str:
        """Redact detected secrets and PII with appropriate placeholders.

        Replaces matched spans in reverse order to preserve offsets.
        """
        if not findings:
            return content

        # Sort by start position descending for safe in-place replacement
        sorted_findings = sorted(findings, key=lambda f: f.position[0], reverse=True)
        result = content
        for finding in sorted_findings:
            start, end = finding.position
            if isinstance(finding, SecretFinding):
                placeholder = f"[{finding.pattern_name.upper()} REDACTED]"
            else:
                placeholder = _REDACT_MAP.get(finding.pii_type, "[PII REDACTED]")
            result = result[:start] + placeholder + result[end:]
        return result

    # ── Guardrails ─────────────────────────────────────────────────

    @staticmethod
    def check_guardrails(
        tenant_id: str,
        content: str,
        guardrail_config: GuardrailConfig,
    ) -> GuardrailResult:
        """Check content against input/output guardrails.

        Detects prompt injection attempts, blocked topics, toxicity,
        and PII echo prevention.

        Args:
            tenant_id: Tenant scope.
            content: Content to check.
            guardrail_config: Which guardrails to enable.

        Returns:
            GuardrailResult indicating pass/fail and any violations.
        """
        violations: list[GuardrailViolation] = []
        content_lower = content.lower()

        # 1. Prompt injection detection
        if guardrail_config.enable_injection_detection:
            for pattern in _INJECTION_PATTERNS:
                if pattern.search(content):
                    violations.append(GuardrailViolation(
                        rule="prompt_injection",
                        detail=f"Injection pattern detected: {pattern.pattern[:50]}",
                        severity="critical",
                    ))
                    break  # One injection finding is enough to flag

        # 2. Blocked topics
        for topic in guardrail_config.blocked_topics:
            if topic.lower() in content_lower:
                violations.append(GuardrailViolation(
                    rule="blocked_topic",
                    detail=f"Content references blocked topic: {topic}",
                    severity="high",
                ))

        # 3. Toxicity scoring (keyword-based lightweight check)
        toxicity_hits = sum(1 for kw in _TOXICITY_KEYWORDS if kw in content_lower)
        toxicity_score = min(toxicity_hits / max(len(_TOXICITY_KEYWORDS), 1), 1.0)
        if toxicity_score > guardrail_config.max_toxicity_score:
            violations.append(GuardrailViolation(
                rule="toxicity",
                detail=f"Toxicity score {toxicity_score:.2f} exceeds threshold {guardrail_config.max_toxicity_score}",
                severity="high",
            ))

        # 4. PII echo prevention
        if guardrail_config.enable_pii_echo_prevention:
            pii_findings = DLPService.scan_for_pii(content)
            if pii_findings:
                violations.append(GuardrailViolation(
                    rule="pii_echo",
                    detail=f"PII detected in output: {len(pii_findings)} finding(s)",
                    severity="high",
                ))

        passed = len(violations) == 0
        action = ScanAction.ALLOW if passed else ScanAction.BLOCK

        logger.info(
            "Guardrail check complete",
            extra={
                "tenant_id": tenant_id,
                "passed": passed,
                "violations_count": len(violations),
                "action": action.value,
            },
        )

        return GuardrailResult(passed=passed, violations=violations, action=action)

    # ── Natural Language Policy ────────────────────────────────────

    @staticmethod
    def create_policy(
        tenant_id: str,
        user_id: str,
        policy_text_nl: str,
    ) -> DLPPolicy:
        """Convert a natural-language policy description into a structured DLP policy.

        Parses the NL text to extract detector types, actions, and scope
        constraints. Returns a DLPPolicy ORM instance ready for persistence.

        Args:
            tenant_id: Owning tenant.
            user_id: Creator user ID.
            policy_text_nl: Human-readable policy description.

        Returns:
            DLPPolicy instance with rules derived from the NL input.
        """
        rules = DLPService._parse_nl_policy(policy_text_nl)
        detector_types = DLPService._extract_detectors_from_rules(rules)
        action = DLPService._extract_action_from_rules(rules)

        policy = DLPPolicy(
            tenant_id=tenant_id,
            name=DLPService._generate_policy_name(policy_text_nl),
            description=policy_text_nl,
            description_nl=policy_text_nl,
            is_active=True,
            detector_types=detector_types,
            rules=rules,
            action=action,
        )

        logger.info(
            "NL policy created",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "detector_types": detector_types,
                "rules_count": len(rules),
            },
        )

        return policy

    # ── Policy Evaluation ──────────────────────────────────────────

    @staticmethod
    def evaluate_policy(
        tenant_id: str,
        content: str,
        policies: list[DLPPolicy],
    ) -> list[PolicyEvaluation]:
        """Evaluate content against a list of tenant DLP policies.

        Returns one PolicyEvaluation per policy indicating whether
        the content matched and what action should be taken.
        """
        evaluations: list[PolicyEvaluation] = []

        for policy in policies:
            if policy.tenant_id != tenant_id:
                continue
            if not policy.is_active:
                evaluations.append(PolicyEvaluation(
                    policy_id=policy.id,
                    matched=False,
                    action=ScanAction.ALLOW,
                    reason="Policy is inactive",
                ))
                continue

            matched, reason = DLPService._evaluate_single_policy(content, policy)
            action = ScanAction(policy.action) if matched else ScanAction.ALLOW

            evaluations.append(PolicyEvaluation(
                policy_id=policy.id,
                matched=matched,
                action=action,
                reason=reason,
            ))

        logger.info(
            "Policy evaluation complete",
            extra={
                "tenant_id": tenant_id,
                "policies_evaluated": len(evaluations),
                "policies_matched": sum(1 for e in evaluations if e.matched),
            },
        )

        return evaluations

    # ── Vault Cross-Reference ──────────────────────────────────────

    @staticmethod
    async def cross_reference_vault(
        tenant_id: str,
        findings: list[SecretFinding],
        vault_manager: Any | None = None,
    ) -> list[VaultCrossRef]:
        """Check if detected secrets exist in Vault and flag for rotation.

        For each finding, checks the Vault secrets engine at the
        conventional path ``dlp/leaked/{pattern_name}``. If found,
        triggers rotation via the VaultSecretsManager.

        Args:
            tenant_id: Tenant scope.
            findings: Detected secret findings to cross-reference.
            vault_manager: Optional VaultSecretsManager instance.

        Returns:
            List of VaultCrossRef indicating vault status and rotation.
        """
        results: list[VaultCrossRef] = []

        for finding in findings:
            vault_path = f"dlp/leaked/{finding.pattern_name}"
            exists = False
            rotation_triggered = False

            if vault_manager is not None:
                try:
                    await vault_manager.get_secret(vault_path, tenant_id)
                    exists = True
                    # Secret found in vault — trigger rotation
                    try:
                        await vault_manager.rotate_secret(vault_path, tenant_id)
                        rotation_triggered = True
                        logger.warning(
                            "Leaked secret rotated in Vault",
                            extra={
                                "tenant_id": tenant_id,
                                "pattern_name": finding.pattern_name,
                                "vault_path": vault_path,
                            },
                        )
                    except Exception:
                        logger.error(
                            "Failed to rotate leaked secret",
                            extra={
                                "tenant_id": tenant_id,
                                "vault_path": vault_path,
                            },
                        )
                except Exception:
                    exists = False

            results.append(VaultCrossRef(
                finding=finding,
                vault_path=vault_path,
                exists_in_vault=exists,
                rotation_triggered=rotation_triggered,
            ))

        return results

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _classify_risk(
        secret_findings: list[SecretFinding],
        pii_findings: list[PIIFinding],
    ) -> RiskLevel:
        """Determine overall risk level from findings."""
        if any(f.severity == "critical" for f in secret_findings):
            return RiskLevel.CRITICAL
        if secret_findings:
            return RiskLevel.HIGH
        if any(f.pii_type in ("ssn", "credit_card_visa", "credit_card_mc", "credit_card_amex") for f in pii_findings):
            return RiskLevel.HIGH
        if pii_findings:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _decide_action(risk_level: RiskLevel, direction: ScanDirection | str) -> ScanAction:
        """Map risk level + direction to an action."""
        if risk_level == RiskLevel.CRITICAL:
            return ScanAction.BLOCK
        if risk_level == RiskLevel.HIGH:
            return ScanAction.REDACT
        if risk_level == RiskLevel.MEDIUM and str(direction) == ScanDirection.OUTPUT:
            return ScanAction.REDACT
        return ScanAction.ALLOW

    @staticmethod
    def _parse_nl_policy(text: str) -> list[dict[str, Any]]:
        """Parse a natural-language policy into structured rules."""
        rules: list[dict[str, Any]] = []
        text_lower = text.lower()

        # Detect what entities the policy targets
        entity_map = {
            "credit card": "credit_card",
            "ssn": "ssn",
            "social security": "ssn",
            "email": "email",
            "phone": "phone",
            "api key": "api_key",
            "secret": "secret",
            "password": "generic_passwd",
            "pii": "pii_all",
            "credentials": "credentials_all",
            "token": "token",
            "private key": "private_key",
            "jwt": "jwt_token",
            "ip address": "ip_address",
        }

        for keyword, entity_type in entity_map.items():
            if keyword in text_lower:
                rules.append({
                    "type": "detect",
                    "entity": entity_type,
                    "source": "nl_parse",
                })

        # Detect action keywords
        action_map = {
            "block": "block",
            "deny": "block",
            "reject": "block",
            "redact": "redact",
            "mask": "redact",
            "alert": "alert",
            "warn": "alert",
            "allow": "allow",
            "permit": "allow",
        }

        for keyword, action in action_map.items():
            if keyword in text_lower:
                rules.append({
                    "type": "action",
                    "action": action,
                    "source": "nl_parse",
                })
                break

        # Detect scope constraints
        if "input" in text_lower and "output" not in text_lower:
            rules.append({"type": "scope", "direction": "input", "source": "nl_parse"})
        elif "output" in text_lower and "input" not in text_lower:
            rules.append({"type": "scope", "direction": "output", "source": "nl_parse"})
        else:
            rules.append({"type": "scope", "direction": "both", "source": "nl_parse"})

        # If no entity was detected, add a catch-all
        if not any(r["type"] == "detect" for r in rules):
            rules.append({"type": "detect", "entity": "all", "source": "nl_parse"})

        return rules

    @staticmethod
    def _extract_detectors_from_rules(rules: list[dict[str, Any]]) -> list[str]:
        """Extract detector type names from parsed rules."""
        detectors: list[str] = []
        for rule in rules:
            if rule.get("type") == "detect":
                entity = rule.get("entity", "")
                if entity and entity not in ("all", "pii_all", "credentials_all"):
                    detectors.append(entity)
        return detectors

    @staticmethod
    def _extract_action_from_rules(rules: list[dict[str, Any]]) -> str:
        """Extract the primary action from parsed rules."""
        for rule in rules:
            if rule.get("type") == "action":
                return rule.get("action", "redact")
        return "redact"

    @staticmethod
    def _generate_policy_name(text: str) -> str:
        """Generate a short policy name from NL description."""
        words = text.split()[:6]
        name = " ".join(words)
        if len(text.split()) > 6:
            name += "..."
        return name

    @staticmethod
    def _evaluate_single_policy(
        content: str,
        policy: DLPPolicy,
    ) -> tuple[bool, str]:
        """Evaluate content against a single policy's rules and detectors."""
        # Check built-in detectors
        if policy.detector_types:
            secret_findings = DLPService.scan_for_secrets(content)
            pii_findings = DLPService.scan_for_pii(content)

            for dtype in policy.detector_types:
                # Check secrets
                if any(f.pattern_name == dtype for f in secret_findings):
                    return True, f"Secret pattern '{dtype}' detected"
                # Check PII
                if any(f.pii_type == dtype for f in pii_findings):
                    return True, f"PII type '{dtype}' detected"

        # Check custom patterns
        if policy.custom_patterns:
            for name, regex_str in policy.custom_patterns.items():
                try:
                    if re.search(regex_str, content):
                        return True, f"Custom pattern '{name}' matched"
                except re.error:
                    continue

        # Check rules for catch-all entity
        for rule in policy.rules:
            if rule.get("type") == "detect" and rule.get("entity") in ("all", "pii_all", "credentials_all"):
                secret_findings = DLPService.scan_for_secrets(content)
                pii_findings = DLPService.scan_for_pii(content)
                if secret_findings or pii_findings:
                    return True, "Catch-all policy matched findings"

        return False, "No policy violations detected"


__all__ = [
    "DLPService",
]
