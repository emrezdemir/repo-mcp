{{- define "repo-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "repo-mcp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "repo-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "repo-mcp.labels" -}}
helm.sh/chart: {{ include "repo-mcp.chart" . }}
{{ include "repo-mcp.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "repo-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "repo-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "repo-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "repo-mcp.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "repo-mcp.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}

{{- define "repo-mcp.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "repo-mcp.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Environment shared by both services. The cache and repo roots must match the
volume mounts, and both services must agree on them: the engine's exact-build
admission barrier is keyed on the canonical cache root.
*/}}
{{- define "repo-mcp.commonEnv" -}}
- name: CBM_CACHE_ROOT
  value: /var/lib/repo-mcp/cache
- name: CBM_REPO_ROOT
  value: /var/lib/repo-mcp/repos
- name: CBM_BINARY
  value: /usr/local/bin/codebase-memory-mcp
{{- end -}}

{{- define "repo-mcp.secretEnv" -}}
{{- $secret := include "repo-mcp.secretName" . -}}
{{- range $key := list "GITHUB_TOKEN" "GITLAB_TOKEN" "BITBUCKET_APP_PASSWORD" "WEBHOOK_SECRET_GITHUB" "WEBHOOK_SECRET_GITLAB" "WEBHOOK_SECRET_BITBUCKET" "CI_TRIGGER_TOKEN" "LITELLM_API_KEY" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $key }}
      optional: true
{{- end }}
{{- end -}}
