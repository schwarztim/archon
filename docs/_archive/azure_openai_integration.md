# Azure OpenAI Integration

## Overview
Archon integrates Azure OpenAI as a first-class provider (`provider=azure_openai`) with model registry entries, routing rules, and validation tooling. The integration seeds 26 Azure deployments, configures provider credentials, and validates connectivity with a dedicated wiring script.

## Architecture

### Provider Type
- Provider identifier: `azure_openai`
- Credential schema fields: `api_key`, `endpoint_url`, `deployment_name`, `api_version`

### Model Registry
Models are stored in `model_registry` as `ModelRegistryEntry` records with:
- `name`, `provider`, `model_id`
- `capabilities` (array), `context_window`, `supports_streaming`
- `cost_per_input_token`, `cost_per_output_token`
- `speed_tier`, `avg_latency_ms`
- `data_classification`, `is_on_prem`, `is_active`, `health_status`
- `config` JSON: `deployment_name`, `api_version`, `endpoint`

### Routing Rules
The Azure integration defines 5 routing rules in `routing_rules` with weighted strategies:
- Strategies: `cost_optimized`, `performance_optimized`, `balanced`
- Weights: `weight_cost`, `weight_latency`, `weight_capability`, `weight_sensitivity`
- Conditions: JSON filter criteria (e.g., `task_type=code`)
- Fallback chain: ordered list of model identifiers

## Setup Instructions

### 1. Environment Variables
Set these variables in `.env` (see `env.example`):

```dotenv
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_openai_api_key
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

### 2. Register Models + Routing Rules
Seed the Azure model registry and routing rules:

```bash
PYTHONPATH=backend python -m scripts.register_azure_models
```

### 3. Validate Wiring
Run validation (optionally include pytest wiring tests):

```bash
python scripts/validate_azure_wiring.py
python scripts/validate_azure_wiring.py --pytest
```

Validation output is saved to `azure_validation_results.json`.

## Model Deployments (26)

| Category | Deployment / Model ID | Capabilities |
| --- | --- | --- |
| Chat | model-router | chat, routing |
| Chat | modelrouter | chat, routing |
| Chat | gpt-5.2 | chat, code, vision, function_calling |
| Chat | gpt-5.2-chat | chat |
| Chat | gpt-5-mini | chat, code, function_calling |
| Chat | gpt-5-chat | chat |
| Chat | qrg-gpt-4.1 | chat, code, vision, function_calling |
| Chat | qrg-gpt-4.1-mini | chat, code, function_calling |
| Chat | gpt-4 | chat, vision, function_calling |
| Chat | gpt-4o-mini | chat, function_calling |
| Codex | gpt-5.2-codex | code, chat, function_calling |
| Codex | gpt-5.1-codex-max | code, chat, function_calling |
| Codex | gpt-5.1-codex-mini | code, chat |
| Reasoning | o1-experiment | reasoning, chat |
| Reasoning | qrg-o3-mini | reasoning, chat |
| Reasoning | o1-mini | reasoning, chat |
| Embedding | text-embedding-3-small-sandbox | embedding |
| Embedding | text-embedding-3-large-sandbox | embedding |
| Embedding | qrg-embedding-experimental | embedding |
| Specialty | gpt-realtime | realtime, streaming |
| Specialty | gpt-4o-mini-realtime-preview | realtime, streaming |
| Specialty | whisper-sandbox | speech-to-text |
| Legacy | qrg-gpt35turbo16k-experimental | chat |
| Legacy | qrg-gpt35turbo4k-experimental | chat |
| Legacy | qrg-gpt4turbo-experimental | chat, vision, function_calling |
| Legacy | qrg-gpt4o-experimental | chat, vision, function_calling |

## Routing Rules (5)

| Rule | Strategy | Conditions | Weights (cost/latency/capability/sensitivity) | Fallback Chain |
| --- | --- | --- | --- | --- |
| cost-optimized-default | cost_optimized | — | 0.6 / 0.15 / 0.15 / 0.1 | gpt-4o-mini → gpt-5-mini |
| code-generation | performance_optimized | task_type=code | 0.1 / 0.2 / 0.6 / 0.1 | gpt-5.2-codex → gpt-5.1-codex-max |
| reasoning-tasks | performance_optimized | task_type=reasoning | 0.1 / 0.1 / 0.7 / 0.1 | o1-experiment → qrg-o3-mini |
| embedding-pipeline | balanced | task_type=embedding | 0.3 / 0.4 / 0.25 / 0.05 | text-embedding-3-small-sandbox |
| high-volume | cost_optimized | volume=high | 0.5 / 0.25 / 0.2 / 0.05 | gpt-5-mini → gpt-4o-mini |

## Testing Instructions
1. Ensure `.env` is configured with Azure credentials.
2. Run the validation script to confirm environment checks and connectivity.
3. Optionally run pytest wiring tests via `--pytest`.

## Troubleshooting
- **Missing environment variables**: Ensure `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_API_VERSION` are set.
- **401 Unauthorized**: Verify the API key and that the key has access to the Azure OpenAI resource.
- **404 Not Found**: Confirm the endpoint URL is correct and includes the Azure resource hostname.
- **Model routing failures**: Ensure `scripts.register_azure_models` has seeded the model registry.
- **Validation import errors**: Run the validation script from the repository root and verify `PYTHONPATH` or backend structure.
