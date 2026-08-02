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

{{/*
The image tag, with the production guard from
docs/adr/0008-environments-and-promotion.md. A mutable tag makes "which commit
is running" unanswerable at exactly the moment it matters, and it turns a
rollback into a rebuild. Failing at template time costs a minute.

Both services share one tag: the engine refuses to run mixed builds against a
shared cache root, so a half-upgraded release is not a supported state.
*/}}
{{- define "repo-mcp.imageTag" -}}
{{- /* Released images are tagged v<appVersion>, matching the git tag. */ -}}
{{- $tag := .Values.image.tag | default (printf "v%s" .Chart.AppVersion) -}}
{{- if eq .Values.environment "production" -}}
{{- if or (not $tag) (has $tag (list "latest" "dev" "dev-latest" "main" "edge")) -}}
{{- fail (printf "environment=production refuses the image tag %q: production must run an immutable tag (v1.2.0, or sha-<commit>). See docs/environments.md" $tag) -}}
{{- end -}}
{{- end -}}
{{- $tag -}}
{{- end -}}

{{/*
gateway and indexer are separate images built from one Dockerfile, so the
repository is a base and the component is a suffix — matching what CI
publishes.
*/}}
{{- define "repo-mcp.gatewayImage" -}}
{{- printf "%s-gateway:%s" .Values.image.repository (include "repo-mcp.imageTag" .) -}}
{{- end -}}

{{- define "repo-mcp.indexerImage" -}}
{{- printf "%s-indexer:%s" .Values.image.repository (include "repo-mcp.imageTag" .) -}}
{{- end -}}

{{/*
Refuse a release that cannot possibly work, rather than one that starts and
then answers every request with a configuration error.
*/}}
{{- define "repo-mcp.validate" -}}
{{- if and (not .Values.database.url) (not .Values.secrets.existingSecret) -}}
{{- fail "set database.url, or point secrets.existingSecret at a secret carrying DATABASE_URL: repo-mcp keeps its configuration in PostgreSQL (docs/adr/0006-configuration-in-the-database.md)" -}}
{{- end -}}
{{- if and (not .Values.secretsKey) (not .Values.secrets.existingSecret) -}}
{{- fail "set secretsKey (repo-mcp-admin generate-key), or supply SECRETS_KEY through secrets.existingSecret: provider tokens are encrypted at rest with it" -}}
{{- end -}}
{{- if and (eq .Values.environment "production") .Values.migrations.auto -}}
{{- fail "migrations.auto is not for production: run the migration as a deliberate step, then deploy. See docs/environments.md" -}}
{{- end -}}
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
- name: ENVIRONMENT
  value: {{ default "unspecified" .Values.environment | quote }}
{{- end -}}

{{/*
How a process reaches its configuration. DATABASE_URL and SECRETS_KEY are
never inlined: both come from the secret, whether the chart rendered it or an
operator supplied one.
*/}}
{{- define "repo-mcp.databaseEnv" -}}
{{- $secret := include "repo-mcp.secretName" . -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: DATABASE_URL
- name: SECRETS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: SECRETS_KEY
- name: DATABASE_POOL_SIZE
  value: {{ .Values.database.poolSize | quote }}
- name: DATABASE_POOL_MAX_OVERFLOW
  value: {{ .Values.database.poolMaxOverflow | quote }}
- name: DATABASE_CONNECT_RETRY_SECONDS
  value: {{ .Values.database.connectRetrySeconds | quote }}
- name: CONFIG_POLL_SECONDS
  value: {{ .Values.database.configPollSeconds | quote }}
{{- end -}}

{{- define "repo-mcp.secretEnv" -}}
{{- $secret := include "repo-mcp.secretName" . -}}
{{- range $key := list "WEBHOOK_SECRET_GITHUB" "WEBHOOK_SECRET_GITLAB" "WEBHOOK_SECRET_BITBUCKET" "CI_TRIGGER_TOKEN" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $key }}
      optional: true
{{- end }}
{{- end -}}
