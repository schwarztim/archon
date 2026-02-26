"""Credential schemas for each connector type — drives type-specific forms."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    """Widget type for a credential field."""

    TEXT = "text"
    PASSWORD = "password"
    SELECT = "select"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    OAUTH = "oauth"


class CredentialField(BaseModel):
    """Single field in a connector's credential schema."""

    name: str
    label: str
    field_type: FieldType = FieldType.TEXT
    required: bool = True
    placeholder: str = ""
    default: str | None = None
    options: list[str] = Field(default_factory=list)
    secret: bool = False
    description: str = ""


class ConnectorTypeSchema(BaseModel):
    """Full schema for a connector type including credential fields."""

    name: str
    label: str
    category: str
    icon: str = "plug"
    description: str = ""
    auth_methods: list[str] = Field(default_factory=list)
    credential_fields: list[CredentialField] = Field(default_factory=list)
    supports_oauth: bool = False
    supports_test: bool = True


# ── Registry of 35+ connector types ─────────────────────────────────

def _db_fields(
    default_port: str,
    *,
    extra: list[CredentialField] | None = None,
) -> list[CredentialField]:
    """Common database credential fields."""
    fields = [
        CredentialField(name="host", label="Host", placeholder="localhost"),
        CredentialField(name="port", label="Port", field_type=FieldType.NUMBER, placeholder=default_port, default=default_port),
        CredentialField(name="database", label="Database", placeholder="mydb"),
        CredentialField(name="username", label="Username", placeholder="user"),
        CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True),
        CredentialField(name="ssl", label="SSL Mode", field_type=FieldType.SELECT, options=["disable", "require", "verify-ca", "verify-full"], required=False, default="disable"),
    ]
    if extra:
        fields.extend(extra)
    return fields


CONNECTOR_TYPE_REGISTRY: list[ConnectorTypeSchema] = [
    # ── Databases ────────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="postgresql", label="PostgreSQL", category="Database",
        icon="database", description="PostgreSQL relational database",
        auth_methods=["basic", "service_account"],
        credential_fields=_db_fields("5432"),
    ),
    ConnectorTypeSchema(
        name="mysql", label="MySQL", category="Database",
        icon="database", description="MySQL relational database",
        auth_methods=["basic"],
        credential_fields=_db_fields("3306"),
    ),
    ConnectorTypeSchema(
        name="mongodb", label="MongoDB", category="Database",
        icon="database", description="MongoDB document database",
        auth_methods=["basic"],
        credential_fields=[
            CredentialField(name="connection_string", label="Connection String", placeholder="mongodb://..."),
            CredentialField(name="database", label="Database", placeholder="mydb"),
            CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="redis", label="Redis", category="Database",
        icon="server", description="Redis in-memory data store",
        auth_methods=["basic"],
        credential_fields=[
            CredentialField(name="host", label="Host", placeholder="localhost"),
            CredentialField(name="port", label="Port", field_type=FieldType.NUMBER, placeholder="6379", default="6379"),
            CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True, required=False),
            CredentialField(name="db", label="DB Number", field_type=FieldType.NUMBER, placeholder="0", default="0", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="elasticsearch", label="Elasticsearch", category="Database",
        icon="search", description="Elasticsearch search and analytics engine",
        auth_methods=["basic", "api_key"],
        credential_fields=[
            CredentialField(name="hosts", label="Hosts (comma-separated)", placeholder="https://localhost:9200"),
            CredentialField(name="username", label="Username", required=False),
            CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True, required=False),
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="snowflake", label="Snowflake", category="Database",
        icon="snowflake", description="Snowflake cloud data warehouse",
        auth_methods=["basic", "service_account"],
        credential_fields=[
            CredentialField(name="account", label="Account Identifier", placeholder="orgname-accountname"),
            CredentialField(name="warehouse", label="Warehouse", placeholder="COMPUTE_WH"),
            CredentialField(name="database", label="Database"),
            CredentialField(name="schema_name", label="Schema", placeholder="PUBLIC", required=False),
            CredentialField(name="username", label="Username"),
            CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="bigquery", label="BigQuery", category="Database",
        icon="chart", description="Google BigQuery analytics",
        auth_methods=["service_account"],
        credential_fields=[
            CredentialField(name="project_id", label="Project ID", placeholder="my-gcp-project"),
            CredentialField(name="dataset", label="Dataset", placeholder="my_dataset", required=False),
            CredentialField(name="credentials_json", label="Service Account JSON", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    # ── SaaS ─────────────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="salesforce", label="Salesforce", category="SaaS",
        icon="cloud", description="Salesforce CRM integration",
        auth_methods=["oauth2"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with Salesforce", field_type=FieldType.OAUTH),
            CredentialField(name="instance_url", label="Instance URL", placeholder="https://myorg.salesforce.com", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="hubspot", label="HubSpot", category="SaaS",
        icon="target", description="HubSpot CRM and marketing platform",
        auth_methods=["oauth2", "api_key"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with HubSpot", field_type=FieldType.OAUTH),
            CredentialField(name="api_key", label="API Key (alternative)", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="zendesk", label="Zendesk", category="SaaS",
        icon="headphones", description="Zendesk customer support platform",
        auth_methods=["api_key", "oauth2"],
        credential_fields=[
            CredentialField(name="subdomain", label="Subdomain", placeholder="mycompany"),
            CredentialField(name="email", label="Email"),
            CredentialField(name="api_token", label="API Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="jira", label="Jira", category="SaaS",
        icon="ticket", description="Jira project management",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="base_url", label="Jira URL", placeholder="https://myorg.atlassian.net"),
            CredentialField(name="email", label="Email"),
            CredentialField(name="api_token", label="API Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="confluence", label="Confluence", category="SaaS",
        icon="book", description="Confluence wiki and documentation",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="base_url", label="Confluence URL", placeholder="https://myorg.atlassian.net/wiki"),
            CredentialField(name="email", label="Email"),
            CredentialField(name="api_token", label="API Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="notion", label="Notion", category="SaaS",
        icon="notebook", description="Notion workspace integration",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="Internal Integration Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    # ── Communication ────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="slack", label="Slack", category="Communication",
        icon="message-square", description="Slack messaging integration",
        auth_methods=["oauth2"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Add to Slack", field_type=FieldType.OAUTH),
            CredentialField(name="channels", label="Default Channels", placeholder="#general, #alerts", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="teams", label="Microsoft Teams", category="Communication",
        icon="users", description="Microsoft Teams integration",
        auth_methods=["oauth2"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with Teams", field_type=FieldType.OAUTH),
            CredentialField(name="tenant_id", label="Azure Tenant ID", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="discord", label="Discord", category="Communication",
        icon="message-circle", description="Discord bot integration",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="bot_token", label="Bot Token", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="guild_id", label="Server (Guild) ID", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="email_smtp", label="Email / SMTP", category="Communication",
        icon="mail", description="Email via SMTP",
        auth_methods=["basic"],
        credential_fields=[
            CredentialField(name="smtp_host", label="SMTP Host", placeholder="smtp.gmail.com"),
            CredentialField(name="smtp_port", label="SMTP Port", field_type=FieldType.NUMBER, placeholder="587", default="587"),
            CredentialField(name="username", label="Username"),
            CredentialField(name="secret_credential", label="Password", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="use_tls", label="Use TLS", field_type=FieldType.CHECKBOX, required=False, default="true"),
        ],
    ),
    # ── Cloud ────────────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="s3", label="AWS S3", category="Cloud",
        icon="cloud", description="Amazon S3 object storage",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(
                name="region", label="Region", field_type=FieldType.SELECT,
                options=["us-east-1", "us-east-2", "us-west-1", "us-west-2",
                         "eu-west-1", "eu-west-2", "eu-central-1",
                         "ap-southeast-1", "ap-northeast-1"],
                default="us-east-1",
            ),
            CredentialField(name="bucket", label="Bucket Name"),
            CredentialField(name="access_key", label="Access Key ID", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="secret_key", label="Secret Access Key", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="azure_blob", label="Azure Blob Storage", category="Cloud",
        icon="cloud", description="Azure Blob storage",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="account_name", label="Storage Account Name"),
            CredentialField(name="container", label="Container Name"),
            CredentialField(name="account_key", label="Account Key", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="gcp_storage", label="GCP Cloud Storage", category="Cloud",
        icon="cloud", description="Google Cloud Storage buckets",
        auth_methods=["service_account"],
        credential_fields=[
            CredentialField(name="project_id", label="Project ID"),
            CredentialField(name="bucket", label="Bucket Name"),
            CredentialField(name="credentials_json", label="Service Account JSON", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="github", label="GitHub", category="Cloud",
        icon="github", description="GitHub DevOps integration",
        auth_methods=["oauth2", "api_key"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with GitHub", field_type=FieldType.OAUTH),
            CredentialField(name="organization", label="Organization", required=False),
            CredentialField(name="personal_token", label="Personal Access Token (alternative)", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="gitlab", label="GitLab", category="Cloud",
        icon="git-branch", description="GitLab DevOps integration",
        auth_methods=["api_key", "oauth2"],
        credential_fields=[
            CredentialField(name="base_url", label="GitLab URL", placeholder="https://gitlab.com", default="https://gitlab.com"),
            CredentialField(name="personal_token", label="Personal Access Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    # ── AI ───────────────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="openai", label="OpenAI", category="AI",
        icon="bot", description="OpenAI GPT models",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="organization", label="Organization ID", required=False),
            CredentialField(name="base_url", label="API Base URL", placeholder="https://api.openai.com/v1", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="anthropic", label="Anthropic", category="AI",
        icon="bot", description="Anthropic Claude models",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="ollama", label="Ollama", category="AI",
        icon="cpu", description="Ollama local LLM server",
        auth_methods=["basic"],
        credential_fields=[
            CredentialField(name="base_url", label="Ollama URL", placeholder="http://localhost:11434", default="http://localhost:11434"),
            CredentialField(name="model", label="Default Model", placeholder="llama3", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="huggingface", label="HuggingFace", category="AI",
        icon="brain", description="HuggingFace model hub",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="Access Token", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="pinecone", label="Pinecone", category="AI",
        icon="cpu", description="Pinecone vector database",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="environment", label="Environment", placeholder="us-east-1-aws"),
            CredentialField(name="index_name", label="Index Name", required=False),
        ],
    ),
    # ── Custom ───────────────────────────────────────────────────────
    ConnectorTypeSchema(
        name="webhook", label="Webhook", category="Custom",
        icon="webhook", description="Custom webhook endpoint",
        auth_methods=["api_key", "basic"],
        credential_fields=[
            CredentialField(name="url", label="Webhook URL", placeholder="https://hooks.example.com/..."),
            CredentialField(
                name="method", label="HTTP Method", field_type=FieldType.SELECT,
                options=["POST", "GET", "PUT", "PATCH", "DELETE"], default="POST",
            ),
            CredentialField(name="headers_json", label="Headers (JSON)", placeholder='{"Content-Type":"application/json"}', required=False),
            CredentialField(name="secret_header", label="Auth Header Value", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="rest_api", label="REST API", category="Custom",
        icon="globe", description="Generic REST API integration",
        auth_methods=["api_key", "basic", "oauth2"],
        credential_fields=[
            CredentialField(name="base_url", label="Base URL", placeholder="https://api.example.com"),
            CredentialField(
                name="auth_type", label="Auth Type", field_type=FieldType.SELECT,
                options=["None", "API Key", "Bearer", "Basic", "OAuth2"], default="None",
            ),
            CredentialField(name="auth_key_name", label="Auth Key Name", placeholder="X-API-Key", required=False),
            CredentialField(name="auth_key_value", label="Auth Key Value", field_type=FieldType.PASSWORD, secret=True, required=False),
            CredentialField(name="username", label="Username (Basic)", required=False),
            CredentialField(name="secret_credential", label="Password (Basic)", field_type=FieldType.PASSWORD, secret=True, required=False),
            CredentialField(name="headers_json", label="Custom Headers (JSON)", placeholder='{}', required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="graphql", label="GraphQL", category="Custom",
        icon="code", description="GraphQL API endpoint",
        auth_methods=["api_key", "basic"],
        credential_fields=[
            CredentialField(name="endpoint", label="GraphQL Endpoint", placeholder="https://api.example.com/graphql"),
            CredentialField(name="auth_header", label="Authorization Header", field_type=FieldType.PASSWORD, secret=True, required=False),
        ],
    ),
    # ── Additional types (Microsoft 365, Google) ─────────────────────
    ConnectorTypeSchema(
        name="microsoft365", label="Microsoft 365", category="SaaS",
        icon="briefcase", description="Microsoft 365 suite integration",
        auth_methods=["oauth2"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with Microsoft", field_type=FieldType.OAUTH),
            CredentialField(name="tenant_id", label="Azure AD Tenant ID", required=False),
        ],
    ),
    ConnectorTypeSchema(
        name="google", label="Google Workspace", category="SaaS",
        icon="mail", description="Google Workspace (Drive, Sheets, etc.)",
        auth_methods=["oauth2"],
        supports_oauth=True,
        credential_fields=[
            CredentialField(name="oauth_connect", label="Connect with Google", field_type=FieldType.OAUTH),
        ],
    ),
    # ── Extra types to reach 35+ ─────────────────────────────────────
    ConnectorTypeSchema(
        name="weaviate", label="Weaviate", category="AI",
        icon="cpu", description="Weaviate vector database",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="url", label="Cluster URL", placeholder="https://my-cluster.weaviate.network"),
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True),
        ],
    ),
    ConnectorTypeSchema(
        name="datadog", label="Datadog", category="SaaS",
        icon="chart", description="Datadog monitoring and analytics",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="api_key", label="API Key", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="app_key", label="Application Key", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="site", label="Datadog Site", field_type=FieldType.SELECT, options=["datadoghq.com", "datadoghq.eu", "us3.datadoghq.com", "us5.datadoghq.com"], default="datadoghq.com"),
        ],
    ),
    ConnectorTypeSchema(
        name="twilio", label="Twilio", category="Communication",
        icon="phone", description="Twilio SMS and voice communications",
        auth_methods=["api_key"],
        credential_fields=[
            CredentialField(name="account_sid", label="Account SID"),
            CredentialField(name="auth_token", label="Auth Token", field_type=FieldType.PASSWORD, secret=True),
            CredentialField(name="from_number", label="From Phone Number", placeholder="+1234567890", required=False),
        ],
    ),
]


def get_connector_schema(name: str) -> ConnectorTypeSchema | None:
    """Look up a connector type schema by name."""
    for schema in CONNECTOR_TYPE_REGISTRY:
        if schema.name == name:
            return schema
    return None


def get_secret_field_names(connector_type: str) -> list[str]:
    """Return the names of fields marked as secret for a connector type."""
    schema = get_connector_schema(connector_type)
    if schema is None:
        return []
    return [f.name for f in schema.credential_fields if f.secret]
