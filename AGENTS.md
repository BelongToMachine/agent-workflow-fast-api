# Repository Agent Rules

## Frontend source of truth and synchronization

**Do not edit frontend code in this monorepo.** This rule is mandatory until the user explicitly approves a separate production-deployment migration.

- The standalone repository `BelongToMachine/agent-workflow-react-front` remains the canonical source for frontend implementation and frontend production builds/deployments. Cloudflare Pages and the SG VPS frontend pipeline remain connected to/configured for that repository.
- Treat `frontend/` in this monorepo as a read-only mirror. Do not create, modify, delete, rename, reformat, or generate files under it here—not even for a small fix. Do not run tools that rewrite files there.
- If asked to change frontend behavior while working from this monorepo, make the change in the standalone frontend repository first. Commit and push it there through that repository's normal workflow; Pages will continue to deploy from its existing source.
- Then synchronize the frontend into this monorepo from the repository root with `git subtree pull`. The current Pages production branch is `agent/migrate-react-frontend`:
  ```bash
  git subtree pull --prefix=frontend frontend-origin agent/migrate-react-frontend
  ```
- Do not add `--squash`; preserve the original frontend commit history. Follow the repository's existing policy when pushing the resulting monorepo commit.
- A normal push to this monorepo does not update the standalone frontend repository and does not trigger its Pages deployment. Do not use `git subtree push` as the normal workflow.
- Do not change Cloudflare Pages repository/root/build settings or the SG VPS frontend deployment source as part of a routine frontend update. Any production-source migration must be a separate, explicitly approved and tested task.
- If `git subtree pull` reports conflicts, do not resolve them by hand-editing `frontend/` in this repository. Reconcile the changes in the standalone source repository, then retry the subtree sync.
- Keep FastAPI code at the repository root. Backend release packaging must continue to exclude `frontend/`.

The nested `frontend/AGENTS.md` was imported from the standalone frontend repository and describes that app's coding conventions. In this monorepo, it does not authorize direct edits to `frontend/`; this root synchronization rule governs how that directory may be updated.
