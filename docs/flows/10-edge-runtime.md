# 10 — Edge Runtime Flow

## Overview
Edge device management with device registration, offline JWT tokens, local secrets bundles via Vault, bidirectional sync with conflict resolution, OTA updates, fleet analytics, and remote command execution.

## Trigger
| Method | Path | Handler |
|--------|------|---------|
| `POST` | `/edge/devices` | register device |
| `POST` | `/edge/devices/{id}/heartbeat` | device heartbeat |
| `POST` | `/edge/devices/{id}/deploy-model` | deploy model |
| `POST` | `/edge/devices/{id}/offline-token` | issue offline token |
| `POST` | `/edge/devices/{id}/sync` | bidirectional sync |
| `POST` | `/edge/devices/{id}/secrets-bundle` | provision secrets |
| `POST` | `/edge/updates` | push OTA update |

## EdgeService
**File:** `services/edge_service.py` — `EdgeService`

### Device Registration
1. Generate `device_fingerprint` = SHA-256 of `"{tenant_id}:{hardware_id}"`
2. Create `EdgeDevice` with hardware specs (cpu_cores, memory_mb, disk_mb, gpu)
3. Audit: `edge.device.registered`

### Offline Auth
- `OfflineToken` with configurable TTL, scoped to device + tenant
- Enables edge operation when cloud connectivity lost

### Local Secrets
- `LocalSecretsBundle` provisioned from Vault
- Encrypted bundle pushed to device
- `SecretsManifest` tracks which secrets are deployed

### Sync Protocol
- `SyncPayload` for bidirectional data exchange
- `SyncConflict` detection and resolution
- `EdgeSyncRecord` for audit trail

## Models
**File:** `models/edge.py`

| Model | Purpose |
|-------|---------|
| `EdgeDevice` | Registered device with hardware specs |
| `OfflineToken` | JWT for offline operation |
| `LocalSecretsBundle` | Vault secrets for edge |
| `EdgeSyncRecord` | Sync audit trail |
| `OTAUpdate` | Over-the-air update manifest |
| `FleetAnalytics` | Fleet-wide metrics |

## Mermaid Sequence Diagram

```mermaid
sequenceDiagram
    participant D as Edge Device
    participant R as routes/edge.py
    participant ES as EdgeService
    participant Vault as SecretsManager
    participant DB as Database

    D->>R: POST /edge/devices {hardware_id, specs}
    R->>ES: register_device(tenant_id, user, device, session, secrets)
    ES->>ES: SHA-256 fingerprint
    ES->>DB: INSERT EdgeDevice
    ES-->>R: EdgeDeviceResponse

    D->>R: POST /edge/devices/{id}/offline-token
    R->>ES: issue_offline_token(tenant_id, device_id, config)
    ES->>ES: Generate scoped JWT
    ES-->>D: OfflineToken

    D->>R: POST /edge/devices/{id}/secrets-bundle
    R->>ES: provision_secrets(tenant_id, device_id, manifest)
    ES->>Vault: get_secret() for each path
    ES->>ES: Encrypt bundle
    ES-->>D: LocalSecretsBundle

    D->>R: POST /edge/devices/{id}/sync
    R->>ES: sync_device(tenant_id, device_id, payload)
    ES->>ES: Detect conflicts
    ES->>DB: Record sync + resolve conflicts
    ES-->>D: SyncResult
```
