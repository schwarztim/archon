# Agent-11: DLP, Guardrails & Natural Language Policy Engine

> **Phase**: 3 | **Dependencies**: Agent-01 (Core Backend), Agent-07 (Orchestration), Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **Every byte of data flowing through any agent passes through this system. Zero tolerance for data leaks.**

---

## Identity

You are Agent-11: the DLP, Guardrails & Policy Engine Guardian. You operate as the data protection layer that intercepts, analyzes, and enforces policy on every input and output flowing through every agent in the platform. You integrate real-time credential scanning with Vault-aware redaction, a 4-layer DLP pipeline, input/output guardrails, and a natural language policy engine that lets administrators write security policies in plain English.

## Mission

Build a production-grade data protection platform that:
1. Scans all LLM inputs AND outputs in real-time for accidentally included secrets, PII, and sensitive data
2. Implements a 4-layer DLP pipeline (regex → NER → semantic classification → OPA policy engine)
3. Cross-references detected secrets against Agent-00's Vault inventory and triggers auto-rotation
4. Enforces input guardrails (prompt injection, topic restriction, profanity, intent classification)
5. Enforces output guardrails (hallucination detection, toxicity, bias, PII echo prevention)
6. Provides a natural language policy engine where admins write policies in plain English, transpiled to OPA Rego
7. Adds <50ms p99 latency per request across the full pipeline
8. Generates real-time monitoring dashboards and compliance reports

## Requirements

### Credential Scanning & Vault-Aware Redaction

**Real-Time Secret Detection**
- Intercepts ALL data flowing through agents — both input (user prompts, tool inputs) and output (LLM responses, tool results)
- Pattern library (200+ regex patterns covering all major cloud providers and services):
  - AWS: `AKIA[0-9A-Z]{16}` (access key), secret access keys, session tokens, ARNs with embedded credentials
  - Azure: connection strings (`DefaultEndpointsProtocol=...`), SAS tokens, client secrets, managed identity tokens
  - GCP: service account JSON (`"type": "service_account"`), API keys (`AIza[0-9A-Za-z-_]{35}`), OAuth refresh tokens
  - GitHub: `ghp_[A-Za-z0-9]{36}` (PAT), `gho_` (OAuth), `ghs_` (app install), `ghr_` (refresh), `github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}`
  - Slack: `xoxb-` (bot), `xoxp-` (user), `xoxs-` (session), `xoxa-` (app-level)
  - Database: `postgresql://user:pass@host`, `mongodb://`, `redis://`, `mysql://`, JDBC connection strings
  - JWT tokens: `eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+`
  - Private keys: RSA (`-----BEGIN RSA PRIVATE KEY-----`), EC (`-----BEGIN EC PRIVATE KEY-----`), Ed25519, OpenSSH format
  - Generic: Stripe keys (`sk_live_`, `pk_live_`), Twilio (`SK[a-z0-9]{32}`), SendGrid, Datadog, New Relic
- Entropy analysis for unknown patterns:
  ```python
  class EntropyAnalyzer:
      """Detect high-entropy strings that may be secrets not matching known patterns."""
      ENTROPY_THRESHOLD = 4.5
      MIN_LENGTH = 20
      MAX_LENGTH = 256

      def shannon_entropy(self, data: str) -> float:
          if not data:
              return 0.0
          entropy = 0.0
          for x in set(data):
              p_x = data.count(x) / len(data)
              entropy -= p_x * math.log2(p_x)
          return entropy

      def scan(self, text: str) -> list[EntropyFinding]:
          findings = []
          for token in self.tokenize(text):
              if self.MIN_LENGTH <= len(token) <= self.MAX_LENGTH:
                  entropy = self.shannon_entropy(token)
                  if entropy > self.ENTROPY_THRESHOLD:
                      findings.append(EntropyFinding(
                          value_hash=hashlib.sha256(token.encode()).hexdigest(),
                          entropy=entropy, length=len(token),
                      ))
          return findings
  ```

**Vault-Aware Cross-Reference & Auto-Rotation**
- When a secret is detected in agent output, cross-reference against Agent-00's Vault inventory:
  ```python
  class VaultAwareRedactor:
      """Cross-reference detected secrets with Vault to identify owner and trigger rotation."""
      def __init__(self, vault_client: VaultClient):
          self.vault_client = vault_client
          self.secret_index = {}  # hash → vault_path cache, rebuilt every 5 min

      async def identify_and_act(self, detected_secret: str, context: DLPContext) -> RedactionResult:
          secret_hash = hashlib.sha256(detected_secret.encode()).hexdigest()
          vault_path = await self.vault_client.lookup_by_hash(secret_hash)

          if vault_path:
              # Log the Vault path (NOT the secret value) for audit
              await self.audit_log.record(
                  event="secret_detected_in_output",
                  vault_path=vault_path,
                  agent_id=context.agent_id,
                  execution_id=context.execution_id,
                  action=context.policy.action,  # alert_only | auto_rotate
              )
              if context.policy.action == "auto_rotate":
                  await self.vault_client.rotate_secret(vault_path, reason="leaked_in_agent_output")
                  return RedactionResult(redacted=True, vault_path=vault_path, rotated=True)
              return RedactionResult(redacted=True, vault_path=vault_path, rotated=False)

          # Unknown secret — alert security team
          return RedactionResult(redacted=True, vault_path=None, rotated=False, alert_sent=True)
  ```
- Redaction in output: replace detected secret with `[REDACTED:secret_type:vault_path]` (path only, never value)
- Configurable per-tenant: `alert_only` (log and notify) vs `auto_rotate` (rotate immediately)
- Rotation integrates with Agent-00's rotation pipeline (Vault dynamic secrets, API key regeneration)

### 4-Layer DLP Pipeline

**Layer 1 — Regex Pattern Matching**
- 200+ built-in regex patterns organized by category (PII, credentials, financial, medical, government IDs)
- Per-tenant custom patterns via admin UI and API
- Pattern metadata:
  ```python
  class DLPPattern(BaseModel):
      id: str
      name: str  # "US Social Security Number"
      category: str  # "PII", "CREDENTIAL", "FINANCIAL", "MEDICAL", "GOVERNMENT_ID"
      regex: str  # r"\b\d{3}-\d{2}-\d{4}\b"
      validation_fn: str | None  # Optional Luhn check, checksum validation
      confidence: float  # 0.0-1.0 base confidence for this pattern
      data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
      compliance_tags: list[str]  # ["GDPR", "HIPAA", "PCI-DSS"]
      enabled: bool = True
      tenant_id: uuid.UUID | None  # None = global pattern
  ```
- Configurable per data classification level: RESTRICTED data gets all patterns, PUBLIC data gets only credential patterns
- False positive reduction: validation functions (Luhn for credit cards, checksum for SSNs, format validation for keys)
- Performance: compiled regex cache, parallel pattern evaluation via `re2` for linear-time guarantees

**Layer 2 — Named Entity Recognition (NER via Presidio)**
- Microsoft Presidio integration for PII/PHI detection:
  ```python
  class PresidioNERLayer:
      """Named Entity Recognition layer using Microsoft Presidio."""
      def __init__(self):
          self.analyzer = AnalyzerEngine()
          self.anonymizer = AnonymizerEngine()
          # Register custom recognizers
          self.analyzer.registry.add_recognizer(EmployeeIDRecognizer())
          self.analyzer.registry.add_recognizer(ProjectCodeRecognizer())
          self.analyzer.registry.add_recognizer(InternalProductRecognizer())

      async def analyze(self, text: str, context: DLPContext) -> list[NERFinding]:
          results = self.analyzer.analyze(
              text=text,
              language="en",
              entities=[
                  "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
                  "US_SSN", "CREDIT_CARD", "IBAN_CODE",
                  "IP_ADDRESS", "LOCATION", "DATE_TIME",
                  "MEDICAL_LICENSE", "US_DRIVER_LICENSE",
                  "US_PASSPORT", "NRP",  # Nationality, Religion, Political group
                  "EMPLOYEE_ID", "PROJECT_CODE", "INTERNAL_PRODUCT",  # Custom
              ],
              score_threshold=0.6,
          )
          return [NERFinding(
              entity_type=r.entity_type,
              start=r.start, end=r.end,
              score=r.score,
              text_snippet=text[max(0,r.start-10):r.end+10],  # Context, not raw PII
          ) for r in results]
  ```
- Built-in entity types: person names, SSN, credit cards, IBAN, addresses, phone numbers, email, IP addresses, medical record numbers, driver's licenses, passports, dates of birth
- Custom entity recognizers per organization:
  - Employee IDs (e.g., `EMP-[0-9]{6}`)
  - Project codes (e.g., `PRJ-[A-Z]{3}-[0-9]{4}`)
  - Internal product names (dictionary-based recognizer)
  - Customer account numbers (org-specific format)
- Confidence scoring per detection (0.0-1.0), configurable threshold per entity type
- Multi-language support: English, Spanish, French, German, Japanese, Chinese (configurable per tenant)

**Layer 3 — Semantic Classification**
- Fine-tuned classifier for data sensitivity categorization:
  ```python
  class SemanticClassifier:
      """LLM-based semantic sensitivity classification."""
      CATEGORIES = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]

      async def classify(self, text: str, context: ClassificationContext) -> ClassificationResult:
          # Context-aware: same text may have different sensitivity in different contexts
          prompt = f"""Classify the sensitivity of the following text.
          Context: Agent "{context.agent_name}" in department "{context.department}"
          Data source: {context.data_source}
          User role: {context.user_role}

          Text: {text[:2000]}

          Categories:
          - PUBLIC: Safe for external sharing
          - INTERNAL: Internal use only, no business impact if leaked
          - CONFIDENTIAL: Business-sensitive, competitive advantage, customer data
          - RESTRICTED: Regulated data (PII, PHI, PCI), legal/compliance impact

          Respond with category and confidence (0-1)."""

          result = await self.llm.classify(prompt)
          return ClassificationResult(
              category=result.category,
              confidence=result.confidence,
              reasoning=result.reasoning,
              context_factors=context.to_dict(),
          )
  ```
- Context-aware classification: same financial data is CONFIDENTIAL in a marketing agent but RESTRICTED in a compliance agent
- Batch classification for efficiency (classify up to 10 text segments per LLM call)
- Model: fine-tuned on organization-specific labeled data (active learning pipeline)
- Fallback: if LLM classifier unavailable, fall back to Layer 1+2 results with conservative classification

**Layer 4 — OPA Policy Engine**
- Open Policy Agent (OPA) sidecar for policy evaluation:
  ```rego
  package archon.dlp

  import future.keywords.in

  default action = "allow"

  # Block any RESTRICTED data from leaving to non-Finance users
  action = "block" {
      input.classification == "RESTRICTED"
      input.data_category == "FINANCIAL"
      not "finance" in input.user.departments
  }

  # Redact PII in outputs for non-privileged users
  action = "redact" {
      input.direction == "output"
      input.findings[_].entity_type in {"PERSON", "US_SSN", "CREDIT_CARD", "PHONE_NUMBER"}
      not input.user.permissions[_] == "pii:read"
  }

  # Mask partial data (show last 4 digits of SSN)
  action = "mask" {
      input.direction == "output"
      input.findings[_].entity_type == "US_SSN"
      input.user.permissions[_] == "pii:read_partial"
  }

  # Alert on CONFIDENTIAL data access outside business hours
  action = "alert" {
      input.classification == "CONFIDENTIAL"
      not within_business_hours(input.timestamp)
  }

  # Encrypt RESTRICTED data for cross-border transfers
  action = "encrypt" {
      input.classification == "RESTRICTED"
      input.user.location.country != input.data.origin_country
  }
  ```
- Available actions: `allow`, `mask`, `redact`, `block`, `alert`, `encrypt`
- Policy scoping: per agent, per department, per data classification level, per user role
- Default policy bundles:
  - **GDPR**: block PII transfer outside EU, enforce right to erasure, consent-gated data access
  - **HIPAA**: block PHI in non-BAA agent outputs, enforce minimum necessary, log all PHI access
  - **SOC2**: enforce access controls, audit all data access, encryption verification
  - **PCI-DSS**: block cardholder data in agent I/O, mask card numbers, enforce encryption
- Policy evaluation caching: 30-second TTL in Redis for identical policy inputs
- Decision logging: every allow/block/redact decision logged for audit trail

### Natural Language Policy Engine (NEW)

**Plain-English Policy Authoring**
- Administrators write security policies in natural language:
  ```
  "Block any response that contains customer financial data when the user is not in the Finance department."
  "Alert the security team when any agent accesses more than 100 records containing PII in a single execution."
  "Redact all email addresses and phone numbers in agent outputs for users with the 'viewer' role."
  "Block prompt injection attempts that try to override system instructions."
  "Encrypt any RESTRICTED data that crosses geographic boundaries."
  ```

- NL → OPA Rego transpilation via LLM:
  ```python
  class NLPolicyEngine:
      """Transpile natural language policies to OPA Rego."""
      async def transpile(self, nl_policy: str, context: PolicyContext) -> TranspileResult:
          prompt = f"""Convert this natural language security policy to OPA Rego.
          Available input fields: {context.schema_description}
          Available actions: allow, mask, redact, block, alert, encrypt

          Policy: "{nl_policy}"

          Output valid Rego code with comments explaining the logic."""

          rego_code = await self.llm.generate(prompt)
          # Validate generated Rego
          validation = await self.opa_client.validate_policy(rego_code)
          if not validation.valid:
              # Retry with error feedback
              rego_code = await self.retry_with_feedback(nl_policy, rego_code, validation.errors)

          return TranspileResult(
              rego_code=rego_code,
              validation=validation,
              dry_run_results=await self.dry_run(rego_code),
          )

      async def dry_run(self, rego_code: str, sample_size: int = 1000) -> DryRunResult:
          """Test policy against last N interactions to preview impact."""
          interactions = await self.get_recent_interactions(sample_size)
          results = {"allow": 0, "block": 0, "redact": 0, "mask": 0, "alert": 0, "encrypt": 0}
          affected_examples = []
          for interaction in interactions:
              decision = await self.opa_client.evaluate(rego_code, interaction.to_input())
              results[decision.action] += 1
              if decision.action != "allow":
                  affected_examples.append(interaction.summary())
          return DryRunResult(
              total_evaluated=sample_size,
              action_distribution=results,
              affected_examples=affected_examples[:20],
          )
  ```
- Policy validation: syntax check, dry-run against last 1000 interactions, impact preview
- Version control: every policy change tracked with author, timestamp, diff, and approval status
- Approval workflow: draft → review → approved → active (requires security team sign-off)
- Rollback: instant rollback to any previous policy version

### Input Guardrails

**Prompt Injection Detection**
- Multi-layer detection:
  ```python
  class PromptInjectionDetector:
      """Detect prompt injection attempts across multiple detection strategies."""
      async def detect(self, user_input: str, system_prompt: str) -> InjectionResult:
          scores = await asyncio.gather(
              self.heuristic_check(user_input),       # Pattern-based (fast)
              self.classifier_check(user_input),       # Fine-tuned model
              self.perplexity_check(user_input),        # Statistical anomaly
          )
          combined_score = self.ensemble_score(scores)
          return InjectionResult(
              is_injection=combined_score > self.threshold,
              confidence=combined_score,
              detection_method=self.dominant_method(scores),
              details=scores,
          )
  ```
- Heuristic patterns: "ignore previous instructions", "you are now", "system:", delimiters (`---`, `###`), instruction override attempts
- Fine-tuned classifier: trained on injection datasets (>50k examples), updated monthly
- Perplexity analysis: statistical anomaly detection for unusual token patterns

**Topic Restriction**
- Per-agent topic boundaries: configurable allowed topics and forbidden topics
- Zero-shot topic classification: determine if user query is within agent's designated scope
- Graceful redirection: "I'm designed to help with X. For Y, please contact Z."

**Additional Input Guards**
- Profanity and hate speech blocking: multi-language profanity detection with severity scoring
- Language detection: enforce per-agent language restrictions (e.g., English-only for compliance agents)
- User intent classification: classify intent (question, command, creative, adversarial) for routing decisions
- Token limit enforcement: reject inputs exceeding configured token limits per agent
- Rate-based abuse detection: detect patterns of rapid adversarial probing

### Output Guardrails

**Hallucination Detection**
- Cross-reference agent output against source documents:
  ```python
  class HallucinationDetector:
      """Detect fabricated facts, citations, and URLs in LLM output."""
      async def check(self, output: str, sources: list[Document], context: ExecutionContext) -> HallucinationResult:
          checks = await asyncio.gather(
              self.check_citations(output, sources),    # Verify cited sources exist
              self.check_urls(output),                   # Verify URLs are real
              self.check_factual_claims(output, sources),# Cross-ref claims vs sources
              self.check_numerical_claims(output, sources),  # Verify numbers/stats
          )
          return HallucinationResult(
              fabricated_citations=checks[0],
              invalid_urls=checks[1],
              unsupported_claims=checks[2],
              incorrect_numbers=checks[3],
              overall_confidence=self.aggregate_confidence(checks),
          )
  ```

**Factual Consistency**
- NLI-based entailment checking: verify output is entailed by (not contradicted by) source documents
- Contradiction detection: flag when output contradicts known facts in knowledge base

**Toxicity & Bias Detection**
- Toxicity scoring via Detoxify or similar model (threshold configurable per agent)
- Bias detection: demographic (gender, race, age), political, religious bias in generated content
- Severity levels: low (subtle bias) → medium (stereotyping) → high (discriminatory) → critical (hate speech)

**PII Echo Prevention**
- Detect when LLM echoes PII from the user's input back in the output:
  ```python
  class PIIEchoDetector:
      """Detect if the LLM echoed back PII that was present in user input."""
      async def check(self, user_input: str, llm_output: str) -> list[PIIEchoFinding]:
          input_pii = await self.presidio.analyze(user_input)
          output_pii = await self.presidio.analyze(llm_output)
          echoed = []
          for out_entity in output_pii:
              for in_entity in input_pii:
                  if (out_entity.entity_type == in_entity.entity_type and
                      self.fuzzy_match(out_entity.text, in_entity.text)):
                      echoed.append(PIIEchoFinding(
                          entity_type=out_entity.entity_type,
                          action="redact",
                      ))
          return echoed
  ```

**Additional Output Guards**
- Confidence scoring with disclosure: when LLM is uncertain (logprob < threshold), append disclosure
- Response length limits: per-agent configurable max tokens (prevent runaway generation)
- Format enforcement: ensure output matches expected schema (JSON, markdown, etc.)

### Real-Time Monitoring Dashboard

**DLP Event Stream**
- Real-time WebSocket feed of all DLP events (detections, policy decisions, alerts)
- Filterable by: agent, user, event type, severity, action taken, time range
- Event structure:
  ```python
  class DLPEvent(BaseModel):
      id: uuid.UUID
      timestamp: datetime
      event_type: Literal["detection", "policy_decision", "alert", "redaction", "block"]
      direction: Literal["input", "output"]
      agent_id: uuid.UUID
      execution_id: uuid.UUID
      user_id: uuid.UUID
      tenant_id: uuid.UUID
      layer: Literal["regex", "ner", "semantic", "policy"]
      finding_type: str  # "US_SSN", "CREDIT_CARD", "prompt_injection", etc.
      confidence: float
      action_taken: Literal["allow", "mask", "redact", "block", "alert", "encrypt"]
      policy_id: str | None  # OPA policy that triggered the action
      false_positive: bool | None  # Set during review
  ```

**Alert Management**
- Alert lifecycle: `new` → `acknowledged` → `investigating` → `resolved` / `false_positive`
- Alert assignment to security team members
- SLA tracking: time to acknowledge, time to resolve
- False positive feedback loop: mark detections as false positive, retrain models
- Escalation: auto-escalate unacknowledged alerts after configurable timeout

**Policy Effectiveness Metrics**
- Per-policy hit rate: how often each policy triggers
- False positive rate: per pattern, per entity type, per policy
- Detection coverage: percentage of sensitive data caught by each layer
- Latency breakdown: time spent in each DLP layer per request

**Compliance Report Generation**
- Automated compliance reports: GDPR Article 30 records of processing, HIPAA access logs, SOC2 data protection evidence
- Exportable as PDF, CSV, JSON
- Scheduled delivery (daily, weekly, monthly) via email

## Core Data Models

```python
class DLPEvent(SQLModel, table=True):
    """Individual DLP detection or policy enforcement event."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: str  # detection, policy_decision, alert, redaction, block
    direction: str  # input, output
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    layer: str  # regex, ner, semantic, policy
    finding_type: str  # US_SSN, CREDIT_CARD, prompt_injection, etc.
    confidence: float
    action_taken: str  # allow, mask, redact, block, alert, encrypt
    policy_id: str | None
    details: dict  # Layer-specific details (never contains raw PII/secrets)
    false_positive: bool | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None

class DLPPolicy(SQLModel, table=True):
    """OPA policy definition with metadata."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: str
    rego_code: str  # OPA Rego policy source
    nl_source: str | None  # Original natural language (if created via NL engine)
    scope_agent_ids: list[uuid.UUID] | None  # None = all agents
    scope_departments: list[str] | None
    scope_classifications: list[str] | None  # PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED
    status: Literal["draft", "review", "approved", "active", "disabled"]
    version: int = 1
    previous_version_id: uuid.UUID | None
    created_by: uuid.UUID = Field(foreign_key="users.id")
    approved_by: uuid.UUID | None
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None

class DLPAlert(SQLModel, table=True):
    """Alert generated by DLP events requiring human review."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dlp_event_id: uuid.UUID = Field(foreign_key="dlp_events.id")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    status: Literal["new", "acknowledged", "investigating", "resolved", "false_positive"]
    assigned_to: uuid.UUID | None = Field(foreign_key="users.id")
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution_notes: str | None
    escalated: bool = False
    escalated_at: datetime | None
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None

class GuardrailResult(SQLModel, table=True):
    """Result of input/output guardrail evaluation."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    direction: Literal["input", "output"]
    guardrail_type: str  # prompt_injection, hallucination, toxicity, bias, pii_echo
    triggered: bool
    confidence: float
    action_taken: str  # allow, block, flag
    details: dict
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime

class CredentialLeak(SQLModel, table=True):
    """Detected credential leak with Vault cross-reference."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    secret_type: str  # aws_key, github_token, private_key, high_entropy
    vault_path: str | None  # Vault path if identified (never the secret value)
    detection_method: str  # regex, entropy
    action_taken: str  # alert_only, redacted, auto_rotated
    rotated: bool = False
    rotation_timestamp: datetime | None
    status: Literal["open", "resolved", "false_positive"]
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
```

## Output Structure

```
security/dlp/
├── __init__.py
├── pipeline.py                  # Multi-layer DLP pipeline orchestrator
├── config.py                    # DLP configuration (thresholds, timeouts)
├── credential_scanner.py        # Credential detection + entropy analysis
├── vault_redactor.py            # Vault-aware cross-reference + auto-rotation
├── patterns/
│   ├── __init__.py
│   ├── registry.py              # Pattern registry + loader
│   ├── aws.py                   # AWS credential patterns
│   ├── azure.py                 # Azure credential patterns
│   ├── gcp.py                   # GCP credential patterns
│   ├── github.py                # GitHub token patterns
│   ├── database.py              # Database connection string patterns
│   ├── pii.py                   # PII patterns (SSN, CC, phone, etc.)
│   └── custom.py                # Custom pattern management
├── ner/
│   ├── __init__.py
│   ├── presidio_layer.py        # Presidio NER integration
│   ├── custom_recognizers.py    # Organization-specific recognizers
│   └── language_support.py      # Multi-language NER config
├── semantic/
│   ├── __init__.py
│   ├── classifier.py            # LLM-based semantic classifier
│   ├── training.py              # Active learning pipeline
│   └── fallback.py              # Fallback classification logic
├── policies/
│   ├── __init__.py
│   ├── opa_client.py            # OPA sidecar client
│   ├── default_gdpr.rego        # GDPR default policies
│   ├── default_hipaa.rego       # HIPAA default policies
│   ├── default_soc2.rego        # SOC2 default policies
│   ├── default_pci.rego         # PCI-DSS default policies
│   └── evaluator.py             # Policy evaluation + caching
└── nl_engine/
    ├── __init__.py
    ├── transpiler.py            # NL → Rego transpilation
    ├── validator.py             # Rego syntax validation
    └── dry_run.py               # Policy dry-run engine

security/guardrails/
├── __init__.py
├── config.py
├── input/
│   ├── __init__.py
│   ├── prompt_injection.py      # Multi-layer injection detection
│   ├── topic_restriction.py     # Topic boundary enforcement
│   ├── profanity.py             # Profanity/hate speech blocking
│   ├── language_detect.py       # Language detection + filtering
│   ├── intent_classifier.py     # User intent classification
│   └── rate_abuse.py            # Rate-based abuse detection
├── output/
│   ├── __init__.py
│   ├── hallucination.py         # Citation + fact verification
│   ├── factual_consistency.py   # NLI-based entailment checking
│   ├── toxicity.py              # Toxicity scoring (Detoxify)
│   ├── bias.py                  # Demographic/political bias detection
│   ├── pii_echo.py              # PII echo prevention
│   ├── confidence.py            # Confidence scoring + disclosure
│   └── format_enforcer.py       # Output format validation
└── nemo/
    ├── __init__.py
    ├── config.py                # NeMo Guardrails configuration
    └── rails.co                 # Colang rail definitions

backend/app/routers/dlp.py          # DLP API endpoints
backend/app/routers/guardrails.py    # Guardrails API endpoints
backend/app/services/dlp.py         # DLP service layer
backend/app/services/guardrails.py   # Guardrails service layer
backend/app/middleware/dlp.py        # Middleware for automatic DLP on all requests
backend/app/models/dlp.py           # SQLModel data models
frontend/src/components/dlp/
├── DLPDashboard.tsx                 # Main monitoring dashboard
├── EventStream.tsx                  # Real-time event feed
├── AlertManager.tsx                 # Alert review interface
├── PolicyEditor.tsx                 # NL + Rego policy editor
├── PolicyDryRun.tsx                 # Policy dry-run results
├── PatternManager.tsx               # Custom pattern management
├── ComplianceReport.tsx             # Compliance report viewer
└── MetricsPanel.tsx                 # Policy effectiveness metrics
tests/test_dlp/
├── conftest.py                      # Fixtures, test data
├── test_pipeline.py                 # Full pipeline integration tests
├── test_patterns.py                 # Regex pattern accuracy tests
├── test_ner.py                      # Presidio NER tests
├── test_semantic.py                 # Semantic classifier tests
├── test_policies.py                 # OPA policy evaluation tests
├── test_nl_engine.py                # NL → Rego transpilation tests
├── test_credential_scanner.py       # Credential scanning tests
├── test_vault_redactor.py           # Vault cross-reference tests
├── test_prompt_injection.py         # Input guardrail tests
├── test_hallucination.py            # Output guardrail tests
├── test_pii_echo.py                 # PII echo prevention tests
├── test_middleware.py               # DLP middleware tests
└── test_alerts.py                   # Alert lifecycle tests
```

## API Endpoints (Complete)

```
# DLP Pipeline
POST   /api/v1/dlp/scan                             # Scan text through full DLP pipeline
GET    /api/v1/dlp/events                            # List DLP events (paginated, filtered)
GET    /api/v1/dlp/events/{id}                       # Get event details

# DLP Patterns
GET    /api/v1/dlp/patterns                          # List patterns
POST   /api/v1/dlp/patterns                          # Create custom pattern
PUT    /api/v1/dlp/patterns/{id}                     # Update pattern
DELETE /api/v1/dlp/patterns/{id}                     # Delete custom pattern
POST   /api/v1/dlp/patterns/test                     # Test pattern against sample text

# DLP Policies
GET    /api/v1/dlp/policies                          # List policies
POST   /api/v1/dlp/policies                          # Create policy (Rego or NL)
GET    /api/v1/dlp/policies/{id}                     # Get policy details
PUT    /api/v1/dlp/policies/{id}                     # Update policy
DELETE /api/v1/dlp/policies/{id}                     # Delete policy
POST   /api/v1/dlp/policies/{id}/approve             # Approve policy
POST   /api/v1/dlp/policies/{id}/activate            # Activate policy
POST   /api/v1/dlp/policies/{id}/rollback            # Rollback to previous version
POST   /api/v1/dlp/policies/{id}/dry-run             # Dry-run policy against recent interactions
GET    /api/v1/dlp/policies/{id}/versions            # List policy versions

# Natural Language Policy Engine
POST   /api/v1/dlp/nl-policy/transpile               # Transpile NL to Rego
POST   /api/v1/dlp/nl-policy/validate                # Validate transpiled Rego
POST   /api/v1/dlp/nl-policy/preview                 # Preview NL policy impact

# Alerts
GET    /api/v1/dlp/alerts                            # List alerts (paginated, filtered)
GET    /api/v1/dlp/alerts/{id}                       # Get alert details
PATCH  /api/v1/dlp/alerts/{id}                       # Update alert (acknowledge, resolve, etc.)
POST   /api/v1/dlp/alerts/{id}/assign                # Assign alert to user
POST   /api/v1/dlp/alerts/{id}/escalate              # Escalate alert

# Credential Leaks
GET    /api/v1/dlp/credential-leaks                  # List detected credential leaks
GET    /api/v1/dlp/credential-leaks/{id}             # Get leak details
PATCH  /api/v1/dlp/credential-leaks/{id}             # Update leak status
POST   /api/v1/dlp/credential-leaks/{id}/rotate      # Trigger secret rotation

# Guardrails
POST   /api/v1/guardrails/evaluate/input             # Evaluate input guardrails
POST   /api/v1/guardrails/evaluate/output            # Evaluate output guardrails
GET    /api/v1/guardrails/results                    # List guardrail results
GET    /api/v1/guardrails/config/{agent_id}          # Get agent guardrail config
PUT    /api/v1/guardrails/config/{agent_id}          # Update agent guardrail config

# Dashboard & Reporting
GET    /api/v1/dlp/dashboard/summary                 # Dashboard summary metrics
GET    /api/v1/dlp/dashboard/events/stream           # WebSocket real-time event stream
GET    /api/v1/dlp/dashboard/metrics/effectiveness    # Policy effectiveness metrics
GET    /api/v1/dlp/dashboard/metrics/latency          # Pipeline latency breakdown
GET    /api/v1/dlp/reports/compliance/{framework}     # Generate compliance report
GET    /api/v1/dlp/reports/compliance/{framework}/pdf # Download compliance PDF
```

## Verify Commands

```bash
# DLP pipeline importable
cd ~/Scripts/Archon && python -c "from security.dlp.pipeline import DLPPipeline; print('OK')"

# Credential scanner importable
cd ~/Scripts/Archon && python -c "from security.dlp.credential_scanner import CredentialScanner; from security.dlp.vault_redactor import VaultAwareRedactor; print('Credential scanner OK')"

# Pattern registry importable
cd ~/Scripts/Archon && python -c "from security.dlp.patterns.registry import PatternRegistry; print('Patterns OK')"

# NER layer importable
cd ~/Scripts/Archon && python -c "from security.dlp.ner.presidio_layer import PresidioNERLayer; print('NER OK')"

# Semantic classifier importable
cd ~/Scripts/Archon && python -c "from security.dlp.semantic.classifier import SemanticClassifier; print('Semantic OK')"

# OPA policy evaluator importable
cd ~/Scripts/Archon && python -c "from security.dlp.policies.evaluator import PolicyEvaluator; print('OPA OK')"

# NL policy engine importable
cd ~/Scripts/Archon && python -c "from security.dlp.nl_engine.transpiler import NLPolicyTranspiler; print('NL Engine OK')"

# Input guardrails importable
cd ~/Scripts/Archon && python -c "from security.guardrails.input.prompt_injection import PromptInjectionDetector; from security.guardrails.input.topic_restriction import TopicRestrictor; print('Input guardrails OK')"

# Output guardrails importable
cd ~/Scripts/Archon && python -c "from security.guardrails.output.hallucination import HallucinationDetector; from security.guardrails.output.pii_echo import PIIEchoDetector; print('Output guardrails OK')"

# DLP middleware importable
cd ~/Scripts/Archon && python -c "from backend.app.middleware.dlp import DLPMiddleware; print('Middleware OK')"

# Data models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.dlp import DLPEvent, DLPPolicy, DLPAlert, GuardrailResult, CredentialLeak; print('Models OK')"

# API routers importable
cd ~/Scripts/Archon && python -c "from backend.app.routers.dlp import router; from backend.app.routers.guardrails import router; print('Routers OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_dlp/ --tb=short -q

# OPA default policies exist
test $(find ~/Scripts/Archon/security/dlp/policies -name '*.rego' 2>/dev/null | wc -l | tr -d ' ') -ge 4

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.py' security/dlp/ security/guardrails/ || echo 'FAIL'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Regex patterns detect SSN, credit cards, AWS keys, GitHub tokens, private keys with >99% recall
- [ ] Entropy analysis detects high-entropy strings (Shannon > 4.5) not matching known patterns
- [ ] Credential scanner cross-references detected secrets against Vault inventory and identifies Vault path
- [ ] Auto-rotation triggered when leaked secret matches Vault inventory (configurable: alert-only vs auto-rotate)
- [ ] Redaction replaces secrets with `[REDACTED:type:path]` — never logs the actual secret value
- [ ] Presidio NER detects person names, SSN, credit cards, addresses, medical records with confidence >0.6
- [ ] Custom entity recognizers (employee IDs, project codes) work per-org configuration
- [ ] Semantic classifier correctly categorizes PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED for test corpus
- [ ] Context-aware classification: same data different sensitivity in different agent contexts
- [ ] OPA policies correctly enforce allow/mask/redact/block/alert/encrypt actions
- [ ] Default policy bundles for GDPR, HIPAA, SOC2, PCI-DSS are active and tested
- [ ] Natural language policy transpilation produces valid OPA Rego that passes syntax validation
- [ ] NL policy dry-run correctly previews impact against recent interactions
- [ ] Prompt injection detector catches direct injection, indirect injection, and delimiter-based attacks
- [ ] Hallucination detector flags fabricated citations and invalid URLs in test outputs
- [ ] PII echo detector identifies when LLM echoes user PII back in output
- [ ] Toxicity scoring correctly flags harmful content above configured threshold
- [ ] Full 4-layer DLP pipeline adds <50ms p99 latency per request
- [ ] Real-time event stream delivers DLP events within 2 seconds via WebSocket
- [ ] Alert lifecycle (new → acknowledged → resolved/false_positive) works end-to-end
- [ ] False positive feedback reduces future false detections for same pattern
- [ ] Compliance reports generate correctly for GDPR, HIPAA, SOC2, PCI-DSS
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in DLP/guardrails module source code or logs
