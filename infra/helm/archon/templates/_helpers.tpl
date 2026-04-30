{{/*
Expand the name of the chart.
*/}}
{{- define "archon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "archon.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart name + version label.
*/}}
{{- define "archon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels — applied to every resource.
*/}}
{{- define "archon.labels" -}}
helm.sh/chart: {{ include "archon.chart" . }}
{{ include "archon.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: archon
archon.ai/env: {{ .Values.global.archonEnv | default "dev" | quote }}
{{- end }}

{{/*
Selector labels (stable subset of common labels — never changes between revisions).
*/}}
{{- define "archon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "archon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Per-component selector labels.
*/}}
{{- define "archon.backend.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{- define "archon.worker.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{- define "archon.frontend.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{- define "archon.gateway.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: gateway
{{- end }}

{{/*
Service account name.
*/}}
{{- define "archon.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "archon.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image helpers — accept a component image config and render registry/repo:tag.
*/}}
{{- define "archon.image" -}}
{{- $registry := .registry -}}
{{- $repo := .image.repository -}}
{{- $tag := .image.tag | default .appVersion -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end }}

{{- define "archon.backend.image" -}}
{{- include "archon.image" (dict "registry" .Values.global.imageRegistry "image" .Values.backend.image "appVersion" .Chart.AppVersion) -}}
{{- end }}

{{- define "archon.worker.image" -}}
{{- include "archon.image" (dict "registry" .Values.global.imageRegistry "image" .Values.worker.image "appVersion" .Chart.AppVersion) -}}
{{- end }}

{{- define "archon.frontend.image" -}}
{{- include "archon.image" (dict "registry" .Values.global.imageRegistry "image" .Values.frontend.image "appVersion" .Chart.AppVersion) -}}
{{- end }}

{{- define "archon.gateway.image" -}}
{{- include "archon.image" (dict "registry" .Values.global.imageRegistry "image" .Values.gateway.image "appVersion" .Chart.AppVersion) -}}
{{- end }}

{{- define "archon.migration.image" -}}
{{- include "archon.image" (dict "registry" .Values.global.imageRegistry "image" .Values.migration.image "appVersion" .Chart.AppVersion) -}}
{{- end }}

{{/*
Database URL built from values (asyncpg driver — backend uses sqlalchemy[asyncio]).
Password is injected via env from the existingSecret; the URL template carries the
username only. The deployment overrides ARCHON_DATABASE_URL with the secret-bearing
form when an existingSecret is configured.
*/}}
{{- define "archon.databaseUrl" -}}
postgresql+asyncpg://{{ .Values.postgresql.username }}@{{ .Values.postgresql.host }}:{{ .Values.postgresql.port }}/{{ .Values.postgresql.database }}
{{- end }}

{{- define "archon.migrationDatabaseUrl" -}}
postgresql://{{ .Values.postgresql.username }}@{{ .Values.postgresql.host }}:{{ .Values.postgresql.port }}/{{ .Values.postgresql.database }}
{{- end }}

{{/*
Redis URL built from values.
*/}}
{{- define "archon.redisUrl" -}}
redis://{{ .Values.redis.host }}:{{ .Values.redis.port }}/{{ .Values.redis.database | default 0 }}
{{- end }}

{{/*
Common envFrom — configmap + optional app secret.
*/}}
{{- define "archon.commonEnvFrom" -}}
- configMapRef:
    name: {{ include "archon.fullname" . }}
{{- if .Values.secrets.existingAppSecret }}
- secretRef:
    name: {{ .Values.secrets.existingAppSecret }}
{{- end }}
{{- end }}
