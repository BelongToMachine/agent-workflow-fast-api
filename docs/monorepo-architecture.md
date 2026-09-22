# Monorepo architecture and deployment boundaries

## Goals

The repository brings the React/Vite frontend and FastAPI backend together for code review and project completeness, while keeping their runtime, dependency, build, and deployment boundaries separate. This is intentionally a repository-layout change, not a production cutover.

```text
repository root
├── app/                         FastAPI application (kept at its existing path)
├── migrations/                  FastAPI database migrations
├── deploy/                      FastAPI deployment scripts and Caddy config
├── tests/                       FastAPI tests
├── pyproject.toml, uv.lock      Python dependency boundary
├── frontend/                    React + Vite application
│   ├── src/
│   ├── deploy/                  Frontend VPS/Nginx deployment files
│   ├── package.json, bun.lock   Bun dependency boundary
│   └── vite.config.js
└── docs/
```

There is no root JavaScript workspace and no shared lockfile. Python/uv commands run at the repository root; Bun commands run in `frontend/` (or through the root Makefile wrappers). The FastAPI Dockerfile still copies only its existing root-level files and `app/`; it does not copy `frontend/` into the API image.

## Current production source of truth

The monorepo does not currently own either frontend production pipeline:

| Production component | Current source / entry point | Status in this change |
| --- | --- | --- |
| FastAPI on SG VPS | Existing backend checkout; `deploy/deploy-production.sh` defaults to `/home/asianode/src/agent-workflow-fast-api` | Root app location and deployment script are unchanged; no deployment was run |
| Frontend on SG VPS | Existing standalone frontend checkout; `frontend/deploy/deploy-frontend-production.sh` defaults to `/home/asianode/src/asianodeagent-front` | Still points to the old checkout; no source path or server config changed |
| Cloudflare Pages | Existing Pages project connected to the standalone frontend repository | Repository, root directory, build settings, DNS, and environment variables are unchanged |

The imported frontend history is present in this Git repository, but that alone does not change Pages or VPS configuration. The `frontend/` deployment files are versioned copies; do not assume their presence means SG has begun using them. The original frontend repository must remain available for current deployments and rollback.

GitHub Actions in this repository are CI-only: they run static checks, tests, and a frontend build. They have read-only repository permissions and no deploy job, production environment, Cloudflare token, or VPS credential.

## Local development

From the repository root:

```sh
make setup
make infra-up
make dev
```

In another terminal:

```sh
make frontend-install
cp frontend/.env.example frontend/.env.local
make frontend-dev
```

Run the full local verification set with `make check-all`. These commands do not deploy. The frontend and backend retain separate dependency manifests and build tools.

## Production cutover is a separate change

Do not point an existing production deployment at the monorepo merely by changing a checkout path. The current frontend VPS script expects a standalone frontend Git root and archives its root contents; Pages likewise has its own project root and repository integration. A monorepo cutover therefore needs explicit adaptations and independent validation.

If/when requested, handle a cutover as a separate reviewed operation:

1. Keep both original repositories and their deployment checkouts intact.
2. Adapt the SG frontend release script to fetch the monorepo commit, archive only `frontend/` into its frontend release root, and preserve its current release/rollback and health-check behavior.
3. Test that adapted script against a staging release before changing the production source.
4. Change the Cloudflare Pages repository/root-directory configuration in a separate step; preserve the existing build command, output directory, and public environment values, then validate the generated deployment URL before changing custom-domain routing.
5. Verify static asset URLs, API base URL, login/session/CSRF, SPA routing, and both SG and Pages builds; define a rollback to the existing standalone frontend source.
6. Only after explicit approval, switch one production frontend source at a time and record the deployed commit and rollback target.

The current work does none of these steps. It does not alter API behavior, frontend runtime code, production environment variables, DNS, Pages settings, VPS files, containers, databases, or deployed releases.
