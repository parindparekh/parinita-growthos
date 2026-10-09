# Deploy GrowthOS to Kubernetes

The `charts/growthos` Helm chart deploys the real API/console and one background worker. It calls Denizen's hosted model; no GPU or model download is required in this cluster. Helm 3.19+ and Kubernetes 1.25+ APIs are used. The chart has no third-party chart dependencies.

## Prerequisites

- Access to the intended Kubernetes context and permission to install in a dedicated namespace.
- A tested application image in your registry (GHCR or Harbor), with pull access from the cluster.
- A dedicated PostgreSQL database and credentials. Use `postgresql+psycopg://...` for `DATABASE_URL`. Production uses PostgreSQL, not the laptop SQLite database.
- An ingress controller, assigned hostname/DNS and a TLS certificate Secret. Match `publicBaseUrl` to the exact HTTPS hostname. If cert-manager provisions TLS, add its issuer annotation in your private values file.
- A Secret named by `existingSecret`, created through your existing secret-management process in the same namespace. No secrets are templated by Helm.

## Runtime Secret contract

| Key | Purpose |
|---|---|
| `DATABASE_URL` | Dedicated PostgreSQL connection string; URL-encode password characters. Set TLS parameters appropriate to your database. |
| `API_KEY` | Unique bootstrap administrator key, at least 24 random characters. It cannot approve production releases. |
| `API_KEYS` | Optional named credentials: `name:editor\|publisher:key,reviewer:approver:key`. Each key and name must be unique. Alternatively configure OIDC. |
| `TEXT_MODEL_API_KEY` | Denizen inference credential. Use the key verified against the configured endpoint. |
| `SESSION_SECRET` | At least 32 random characters when using OIDC. |
| `OIDC_CLIENT_SECRET` | Only if your configured OIDC client requires one. |

Use `env` in your private values file for non-secret `OIDC_ISSUER`, `OIDC_CLIENT_ID`, roles mapping and related settings. The production example does not invent your company identity settings. Configure least-privilege named identities before production use.

The chart ConfigMap contains only application settings. Secret values override matching settings, so restrict write access to the referenced Secret. Model endpoint/name can be changed with `model.baseUrl` and `model.name` without changing application code. The private laptop model configuration is not part of the image, chart or repository.

## Build and publish the image

From the repository root, use your existing CI registry credentials:

```sh
IMAGE=your-registry/your-project/growthos
TAG=$(git rev-parse HEAD)
docker build --pull -t "$IMAGE:$TAG" .
docker push "$IMAGE:$TAG"
```

Set `image.repository` and `image.tag` to these exact values, or set `image.digest` to the verified image digest. An unbuilt tag is not a deployable image. A manual GitHub Actions packaging workflow is also provided; it publishes to GHCR and uploads a Helm artifact without deploying the cluster.

## Install or upgrade

Copy `deploy/values-production.example.yaml` to a private, operator-managed values file and fill the actual registry, hostname, ingress class, and Secret name. Do not use the example hostname. The chart does not create DNS or issue certificates itself.

```sh
kubectl config current-context
helm lint charts/growthos -f /secure/path/growthos-values.yaml
helm template growthos charts/growthos -n growthos -f /secure/path/growthos-values.yaml > /tmp/growthos-rendered.yaml
kubectl apply --dry-run=server -n growthos -f /tmp/growthos-rendered.yaml
helm upgrade --install growthos charts/growthos \
  --namespace growthos --create-namespace \
  -f /secure/path/growthos-values.yaml --atomic --wait --timeout 15m
helm test growthos -n growthos --logs
kubectl rollout status deployment/growthos-growthos-api -n growthos
```

Create the namespace and runtime Secret before installation; the dry run also needs the namespace. If using a GitOps or Rafay workflow, import the same chart and environment-specific values into that system. Do not create a parallel deployment with a different release name.

Then open `https://YOUR_HOST/console`, sign in, generate a synthetic draft, check source review, and confirm that an unapproved high-risk release cannot publish. The Helm test verifies database readiness and console HTTP availability; it does not verify Denizen, company SSO, publishing destinations or TLS/DNS.

## Database and audio storage

External PostgreSQL is the default. If your cluster has no database service, `postgresql.enabled=true` creates a single PostgreSQL 16 StatefulSet and retained volume claim. Supply `postgresql.existingSecret` containing `POSTGRES_PASSWORD`. Set the application Secret's `DATABASE_URL` to that database's Service (`growthos-growthos-postgresql` for release `growthos`) with matching username/password/database. This option is not an HA database or a backup solution. Its container security IDs assume the supplied Alpine image; review them if replacing that image.

Audio is disabled by default. Set `media.enabled=true` with a ReadWriteMany storage class or `media.existingClaim` backed by shared ReadWriteMany storage. API and worker must see the same files. The created audio PVC is retained on uninstall. A voice provider and consent are separate from storage provisioning.

## Operations

- API readiness checks `/health`, including the database. Liveness checks `/live`, so a database outage does not cause a restart storm.
- The API initializes additive schema changes under a PostgreSQL advisory lock. The worker waits for schema readiness and writes a heartbeat after completed cycles. Worker upgrades use Recreate to avoid overlapping pollers. Long feed batches may require tuning heartbeat probe thresholds.
- The default is one API replica. Multiple replicas require PostgreSQL, shared media if enabled, an ingress-level rate limiter (the app limiter is per process), and a load test. PDB requires at least two replicas. No unverified HPA defaults are supplied.
- Containers are non-root with read-only roots, dropped capabilities, and no mounted Kubernetes API token. Set cluster NetworkPolicy rules for ingress, DNS, PostgreSQL, Denizen HTTPS and enabled publishing destinations according to your network design.
- ConfigMap changes roll pods through a checksum. After a runtime Secret rotation, restart both deployments or use your cluster's approved Secret reloader.
- Back up PostgreSQL and media before upgrading. Prove restore in a separate namespace. This chart does not automate database backups.
- `helm rollback growthos REVISION -n growthos --wait` restores workloads and config, **not database contents**. Review schema compatibility before rollback. Uninstall retains database claim templates and chart-created media storage; deliberate data removal is separate.

## Validation status

Local validation covers Helm lint/render, four installation variants and invalid configuration rejection. Cluster admission, image pull, storage provisioning, DNS/TLS and a live Kubernetes rollout require your real context and have not been verified locally. No kubeconfig or production host is bundled.
