{{- define "growthos.name" -}}
{{- printf "%s-growthos" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- define "growthos.labels" -}}
app.kubernetes.io/name: growthos
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}
{{- define "growthos.image" -}}
{{- $repo := required "image.repository is required" .Values.image.repository -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" $repo .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" $repo (required "image.tag or image.digest is required" .Values.image.tag) }}
{{- end -}}
{{- end -}}
{{- define "growthos.security" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
