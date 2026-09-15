# Asianode MinIO infrastructure

This directory contains the independent object-storage stack. It is not part
of the API release lifecycle and must not be copied into
`releases/<commit>/` as application runtime data.

The current design is one MinIO Compose project per VPS:

```text
application project: asianode-production / asianode-staging
  api + redis

storage project: asianode-minio-production / asianode-minio-staging
  minio
```

The application API and MinIO share the pre-created external Docker network
`asianode-storage`. The API uses `http://minio:9000` from inside Docker. The
host exposes MinIO only on loopback ports `19000` (S3 API) and `19001` (Console),
so public traffic must go through a reviewed HTTPS reverse-proxy rule.

## 1. Install the files on a VPS

For production, copy this directory to:

```text
/home/asianode/asianode-production/infra/minio/
```

For staging, use:

```text
/home/asianode/asianode-staging/infra/minio/
```

Create the persistent data directory outside the release tree:

```bash
install -d -m 700 /home/asianode/asianode-production/shared/minio-data
```

Copy `.env.minio.example` to `.env.minio`, update the environment-specific
paths, and generate unique administrator credentials:

```bash
cp .env.minio.example .env.minio
chmod 600 .env.minio
openssl rand -hex 32
```

For staging, use `asianode-minio-staging`,
`/home/asianode/asianode-staging/...`, and a staging-only credential set.

## 2. Create the shared Docker network

Run once per VPS. The network is deliberately external so the application and
storage Compose projects can communicate without sharing a project lifecycle:

```bash
if ! docker network inspect asianode-storage >/dev/null 2>&1; then
  docker network create asianode-storage
fi
```

## 3. Validate and start MinIO

Run these commands from this directory, using the same rootless Docker context
that runs the API:

The included script is the recommended repeatable path. It checks or creates
the external network, validates Compose, uses the pinned image from the local
Docker cache when available, pulls it only when missing, starts MinIO, and
waits for its healthcheck:

```bash
MINIO_ROOT=/home/asianode/asianode-production \
MINIO_PROJECT_NAME=asianode-minio-production \
bash /home/asianode/asianode-production/infra/minio/deploy-minio.sh
```

For staging:

```bash
MINIO_ROOT=/home/asianode/asianode-staging \
MINIO_PROJECT_NAME=asianode-minio-staging \
bash /home/asianode/asianode-staging/infra/minio/deploy-minio.sh
```

The equivalent manual commands are:

```bash
ENV_FILE=/home/asianode/asianode-production/infra/minio/.env.minio
COMPOSE_FILE=/home/asianode/asianode-production/infra/minio/compose.minio.yaml

docker compose \
  --project-name asianode-minio-production \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config -q

docker compose \
  --project-name asianode-minio-production \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  pull minio

docker compose \
  --project-name asianode-minio-production \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d minio
```

For staging, replace the project name and paths with the staging values. Do
not run `down -v`, remove the bind-mounted data directory, or run a global
Docker prune as part of an application deployment.

Verify the service:

```bash
docker compose \
  --project-name asianode-minio-production \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  ps

curl --fail --silent --show-error \
  http://127.0.0.1:19000/minio/health/ready
```

## 4. Create the bucket and application credentials

Install the MinIO Client (`mc`) on the VPS, then load the two root credentials
from the protected `.env.minio` file for this shell. The root credentials are
for administration only; do not put them in the API `.env.production` or
`.env.staging`.

```bash
ENV_FILE=/home/asianode/asianode-production/infra/minio/.env.minio
set -a
. "$ENV_FILE"
set +a

mc alias set asianode-minio http://127.0.0.1:19000 \
  "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

mc mb --ignore-existing asianode-minio/asianode-knowledge-production
```

Create a bucket-specific policy. Replace `__BUCKET__` with the exact bucket
name; do not use a wildcard that grants access to every bucket:

```bash
sed 's/__BUCKET__/asianode-knowledge-production/g' \
  knowledge-policy.template.json > /tmp/asianode-knowledge-production-policy.json

mc admin policy create \
  asianode-minio asianode-knowledge-production-policy \
  /tmp/asianode-knowledge-production-policy.json
```

Create a dedicated application user with a long random password and attach the
bucket-only policy:

```bash
MINIO_APP_PASSWORD="$(openssl rand -hex 32)"

mc admin user add asianode-minio \
  asianode-api-production "$MINIO_APP_PASSWORD"

mc admin policy attach asianode-minio \
  asianode-knowledge-production-policy \
  --user asianode-api-production
```

Put the resulting application credentials—not the root credentials—in the
production API environment file:

```env
KNOWLEDGE_STORAGE_PROVIDER=s3
KNOWLEDGE_S3_BUCKET=asianode-knowledge-production
KNOWLEDGE_S3_ENDPOINT_URL=http://minio:9000
KNOWLEDGE_S3_REGION=us-east-1
KNOWLEDGE_S3_ACCESS_KEY_ID=asianode-api-production
KNOWLEDGE_S3_SECRET_ACCESS_KEY=<application-password>
```

Use a separate bucket, user, policy, and credential set for staging. The local
Mac API cannot join the VPS Docker network; when local development must use
VPS storage, set its S3 endpoint to the HTTPS Caddy endpoint instead:
`https://storage.asianodeatlas.com` (or a staging-only storage hostname).

## 5. Optional Caddy endpoint

The included `Caddyfile.storage.example` proxies the S3 API hostname to
`127.0.0.1:19000`. Add it to the VPS Caddy configuration only after the DNS
record exists and the intended environment is confirmed. Keep port `19001`
private; expose the Console only through a controlled admin route or an SSH
tunnel.

After changing Caddy, validate and reload it:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## 6. Operational rules

- Upgrade MinIO as a storage-infrastructure change, after testing in staging.
- Back up the MinIO data directory and test restoring a bucket before relying on it.
- Treat a one-VPS, one-drive deployment as persistent storage, not high availability.
- Keep production and staging buckets, users, policies, data paths, and backups separate.
- API deployment scripts may restart `api` and `redis`, but never remove this
  Compose project, its container, its volume, or its data directory.
