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
Create chart name and version as used by the chart label.
*/}}
{{- define "archon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "archon.labels" -}}
helm.sh/chart: {{ include "archon.chart" . }}
{{ include "archon.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "archon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "archon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend selector labels.
*/}}
{{- define "archon.backend.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Frontend selector labels.
*/}}
{{- define "archon.frontend.selectorLabels" -}}
{{ include "archon.selectorLabels" . }}
app.kubernetes.io/component: frontend
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
Backend image.
*/}}
{{- define "archon.backend.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.backend.image.repository -}}
{{- $tag := .Values.backend.image.tag | default .Chart.AppVersion -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end }}

{{/*
Database URL built from values.
*/}}
{{- define "archon.databaseUrl" -}}
postgresql+asyncpg://{{ .Values.postgresql.username }}@{{ .Values.postgresql.host }}:{{ .Values.postgresql.port }}/{{ .Values.postgresql.database }}
{{- end }}

{{/*
Redis URL built from values.
*/}}
{{- define "archon.redisUrl" -}}
redis://{{ .Values.redis.host }}:{{ .Values.redis.port }}/0
{{- end }}
