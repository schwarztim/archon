# Archon SSO Integration Runbook

Operational guide for federating Archon authentication with an external
identity provider via OIDC (preferred) or SAML 2.0. Reference IdP for
this runbook is Keycloak 26 (`docker-compose.yml` ships a dev instance
on port 8180), but the procedures generalize to Okta, Azure AD, Auth0,
and Google Workspace.

## 1. Stack Overview

| Component | Location | Notes |
|-----------|----------|-------|
| Keycloak (dev) | `docker-compose.yml` service `keycloak` | Port 8180, admin/admin, realm config persisted in `dev-file` mode. |
| OIDC client | Configured in IdP, secret stored at `secret/archon/keycloak` | Backend reads via `app/secrets/`. |
| SAML models | `backend/app/models/saml.py` | Pydantic schemas for SAML 2.0 assertions. |
| JWT validation | Backend auth middleware | Reads `signing_key` from `secret/archon/jwt`. |

## 2. Keycloak Realm Setup

### 2.1 Bootstrap a realm via JSON export/import

The recommended pattern is to keep the realm configuration in version
control as JSON:

```bash
# Export the realm from a configured Keycloak instance:
docker compose exec keycloak \
  /opt/keycloak/bin/kc.sh export \
    --dir /tmp/realm-export \
    --realm archon

# Copy to the host:
docker cp $(docker compose ps -q keycloak):/tmp/realm-export \
  ./infra/keycloak/realms/

# Import on a fresh instance:
docker compose exec keycloak \
  /opt/keycloak/bin/kc.sh import --dir /opt/keycloak/data/import
```

Realm export must include:

- The `archon` realm with display name + branding.
- The `archon-backend` OIDC client (see §3).
- Default roles: `archon-admin`, `archon-tenant-admin`, `archon-user`.
- Required actions on first login: `update_password`, `verify_email`.

### 2.2 Realm sanity checks

After import, verify:

```bash
# Realm reachable
curl -sf http://localhost:8180/auth/realms/archon/.well-known/openid-configuration | jq '.issuer'

# Token endpoint advertises HTTPS in production (HTTP only acceptable in dev)
curl -sf http://localhost:8180/auth/realms/archon/.well-known/openid-configuration \
  | jq '.token_endpoint'
```

## 3. OIDC Client Configuration

For each Archon environment (dev, staging, production) configure a
confidential client with these properties:

| Field | Value |
|-------|-------|
| Client ID | `archon-backend` |
| Client Protocol | `openid-connect` |
| Access Type | `confidential` |
| Standard Flow | enabled (Authorization Code + PKCE) |
| Direct Access Grants | disabled (no resource-owner password) |
| Service Accounts | enabled (for backend → Keycloak admin API) |
| Valid Redirect URIs | `https://<archon-host>/auth/callback` |
| Web Origins | `https://<archon-host>` |
| Backchannel Logout URL | `https://<archon-host>/auth/logout-callback` |
| Front-channel Logout | enabled |
| Token Lifespan | `15m` access / `30d` refresh |

### 3.1 Persist the client secret

After creating the client, copy its secret into Vault:

```bash
vault kv put secret/archon/keycloak \
  admin_user="$KEYCLOAK_ADMIN_USER" \
  admin_password="$KEYCLOAK_ADMIN_PASSWORD" \
  client_secret="$KEYCLOAK_CLIENT_SECRET"
```

Backend pulls this at startup; rotation is operator-driven. The dev
`init.sh` seeds placeholder values so the backend can boot without a
real IdP.

### 3.2 Role propagation

Map IdP roles → Archon roles via Keycloak's "Token Claim Name":

| IdP role | Archon role | Token claim |
|----------|-------------|-------------|
| `idp-admin` | `archon-admin` | `roles[]` (realm-level) |
| `idp-tenant-admin` | `archon-tenant-admin` | `roles[]` |
| `idp-user` | `archon-user` | `roles[]` |
| (group claim) | `tenant_id` | `archon_tenant` (custom mapper) |

The Archon backend reads `archon_tenant` to scope the request and
validates that `roles[]` contains at least one Archon-recognized role.

## 4. SAML 2.0 Configuration (Alternative)

For IdPs that only speak SAML (legacy enterprise):

| Field | Value |
|-------|-------|
| Entity ID | `urn:archon:sp` |
| ACS URL | `https://<archon-host>/auth/saml/acs` |
| SLO URL | `https://<archon-host>/auth/saml/sls` |
| NameID Format | `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress` |
| Signature Algorithm | `RSA-SHA256` |
| Want Assertions Signed | yes |
| Want Authn Request Signed | yes |
| Attribute mappings | see `backend/app/models/saml.py::SAMLAttributeMapping` |

The default attribute mapping aligns with the OASIS LDAP profile (oid
`0.9.2342.19200300.100.1.3` for email, `2.5.4.42` for first name, etc.).
Override per-IdP in the realm config when the IdP uses friendly names.

## 5. Test Users + Roles

For development and CI, seed the following users into the `archon` realm:

| Username | Password | Roles | Tenant |
|----------|----------|-------|--------|
| `admin@archon.local` | `admin-test` | `archon-admin` | (none — global) |
| `alice@tenant1.local` | `alice-test` | `archon-tenant-admin` | `tenant1` |
| `bob@tenant1.local` | `bob-test` | `archon-user` | `tenant1` |
| `carol@tenant2.local` | `carol-test` | `archon-user` | `tenant2` |
| `disabled@archon.local` | `disabled-test` | `archon-user`, disabled | `tenant1` |

These usernames are referenced by `backend/tests/test_sso_keycloak.py`
when `KEYCLOAK_TEST_URL` is set. The tests skip cleanly if the realm
is not reachable.

## 6. Troubleshooting Checklist

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `invalid_client` on token exchange | Client secret mismatch between IdP and Vault | Re-copy secret with `vault kv put secret/archon/keycloak client_secret=...`; restart backend. |
| `nonce mismatch` | Replay protection; clock skew >5min | Sync NTP on backend hosts; reduce cookie lifetime. |
| `no_matching_jwk` | Backend cached the previous JWKS | Restart backend or trigger `/auth/refresh-jwks`; Keycloak rotates keys quarterly. |
| Login succeeds, role check fails | Token mapper missing `roles[]` claim | Re-add the "Realm Role" mapper on the client; verify `realm_access.roles` in the access token. |
| `archon_tenant` claim absent | Tenant group mapper not configured | Add a Group Membership mapper, target attribute name `archon_tenant`. |
| SAML "audience mismatch" | SP entity ID differs between IdP metadata and backend config | Align entity IDs in both ends; rotate metadata. |
| Logout leaves backend session live | Backchannel logout not configured | Set "Backchannel Logout URL" in the IdP and confirm the backend exposes `/auth/logout-callback`. |
| Token expired immediately | Access token TTL < clock skew tolerance | Bump access TTL to ≥ 5m or fix host time. |
| Refresh token replay | Refresh tokens are single-use | Ensure the client re-stores the new refresh token after every refresh. |

## 7. Operational Procedures

### 7.1 Rotating the OIDC client secret

```bash
# 1. Rotate in the IdP — generates a new value, do NOT close the dialog.
# 2. Stage the new value in Vault:
vault kv put secret/archon/keycloak client_secret="$NEW_SECRET"
# 3. Trigger a rolling restart of backend pods.
# 4. Confirm /health/auth is green.
# 5. Revoke the old secret in the IdP.
```

Acceptable downtime: zero (the rotation is staged before the
revocation).

### 7.2 Adding a new IdP (multi-tenant federation)

Per-tenant IdPs are stored in `backend/app/models/auth.py` as
`IdPConfig`. To onboard:

1. Capture the IdP's metadata (OIDC discovery URL or SAML XML).
2. Insert an `IdPConfig` row scoped to the tenant.
3. Restart the backend (or hit the admin reload endpoint).
4. Send the redirect URI to the IdP operator.
5. Verify with the per-IdP test in `test_sso_keycloak.py`.

### 7.3 Disabling SSO temporarily

`docker-compose.yml` sets `ARCHON_AUTH_DEV_MODE: "true"` for local dev.
This bypasses IdP validation and signs JWTs with the dev key. NEVER set
this in any environment that handles tenant data.

## 8. Cross-Reference

- Backup Keycloak realm export: see `backup-restore.md` § off-site copies.
- Vault key rotation depending on Keycloak: `disaster-recovery.md` § ransomware.
- SSO integration tests: `backend/tests/test_sso_keycloak.py`.
