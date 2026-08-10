# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project overview

GitOps-driven homelab Kubernetes cluster. A Talos Linux cluster runs on Proxmox VE; it is provisioned with Terragrunt + OpenTofu (`infra/`) and applications are delivered by ArgoCD from this same repo (`platform/` + `apps/`).

Stack: Talos Linux - Kubernetes - Cilium (kube-proxy-free, L2 LB, Gateway API, WireGuard encryption, Hubble) - ArgoCD - cert-manager (Let's Encrypt DNS-01) - external-dns - SOPS/age - Renovate.

## Repository layout

```
infra/              Terragrunt/OpenTofu units: cluster -> addons -> argocd-config
  env.hcl           ALL unit inputs centralized (versions, nodes, secrets)
  root.hcl          shared remote_state (local backend)
  secrets.sops.yaml single SOPS-encrypted secrets file (never plaintext)
  cluster/          Talos cluster + Cilium; writes artifacts/kubeconfig + talosconfig
  addons/           Installs ArgoCD, cert-manager, external-dns
  argocd-config/    ArgoCD ApplicationSets (platform, apps)
platform/           ArgoCD-managed cluster-level resources (network, cert-manager,
                    external-dns, issuer, metrics-server, kubelet-serving-cert-approver)
apps/               ArgoCD-managed applications (one subdir per app)
.github/            pre-commit CI workflow + scripts
.pre-commit-config.yaml  the single lint/format gate
renovate.json       dependency automation
```

## Commands

```sh
pre-commit run --all-files         # run every lint/format gate locally
cd infra && terragrunt validate --all
cd infra && terragrunt plan --all
cd infra && terragrunt apply --all   # CAUTION: mutates the live cluster
cd infra && terragrunt destroy --all # CAUTION: destroys everything
sops infra/secrets.sops.yaml         # edit secrets (re-encrypts on save)
.github/scripts/test-renovate.py     # local Renovate dry-run; verify dep extraction/updates (no branches/PRs)
```

## Validation & pre-commit

Every change must pass `.pre-commit-config.yaml`; CI runs it on push/PR (`.github/workflows/pre-commit.yaml`, pinned tool versions). Notable hooks:

- `terragrunt_fmt` + `terraform_tflint` (config: `infra/cluster/.tflint.hcl`) for `infra/`
- local `terragrunt-validate` hook (`.github/scripts/terragrunt-validate.sh`): `terragrunt validate --all` on `infra/`; skips when no SOPS age key is available (e.g. CI), so it enforces validation locally where secrets decrypt
- `yamllint` (`.yamllint.yaml`; ignores `secrets.sops.yaml`, 160-char lines)
- `kubeconform` on `platform/` and `apps/` YAML
- local `argocd-apps-check` hook (`.github/scripts/check-argocd-apps.py`): for every `Application` manifest under `platform/`/`apps/`, pulls its helm/OCI chart at `targetRevision` and renders it with `helm template` using the manifest's release name, namespace, and values (skips when helm/PyYAML are missing)
- `detect-secrets` (baseline: `.secrets.baseline`); never add plaintext secrets
- `renovate-config-validator` for `renovate.json`
- `ruff-check` (astral-sh/ruff-pre-commit) for Python files
- local `sops-encrypted` hook; `*.sops.yaml` files must be encrypted

## Renovate

`renovate.json` is the single source of truth for dependency scanning. Coverage today:

- `infra/env.hcl` version pins → regex custom managers (`talos_version`, `kubernetes_version`, `cilium_chart_version`, `gateway_api_crds_version`). **Every version field in `env.hcl` MUST have a matching `customManagers` entry.**
- Terraform `helm_release` (ArgoCD in `infra/addons/main.tf`) → `terraform` manager (helm datasource).
- ArgoCD `Application` manifests under `platform/` and `apps/` (cert-manager, external-dns, spegel) → `argocd` manager (helm datasource; OCI charts like cert-manager and spegel resolve via the `docker` datasource on quay.io/ghcr.io).
- Raw manifests (`metrics-server`, `kubelet-serving-cert-approver`) → `kubernetes` manager (image + API versions).
- `.github/workflows/pre-commit.yaml` CLI pins → regex custom managers; `.pre-commit-config.yaml` → `pre-commit` manager.

When adding or removing a component:

- New version pin in `env.hcl` (or any new `*.hcl`/workflow file) → add the corresponding custom manager; on removal, delete the entry.
- New manifests under `platform/` or `apps/` → auto-discovered by the `argocd`/`kubernetes` managers, no config change needed (just ship the manifest).
- Removing an Application/manifest → no config change needed; remove the manifest only.

Verify any change with `.github/scripts/test-renovate.py` before pushing (uses the exact renovate version pinned in `.pre-commit-config.yaml`; requires `gh` auth or `GITHUB_TOKEN`).

- Custom-manager file matching is `managerFilePatterns` in Renovate 44.x (was `fileMatch` before v44). Always validate with the pinned version (`pre-commit run renovate-config-validator --all-files`); a stale `npx` cache can silently run an old renovate and report false errors.
- Local dry-runs need Node matching renovate's engine (44.x: `^24.11.0`; use the pre-commit `node_env-lts` node if the system node is too new) and a GitHub token via `RENOVATE_HOST_RULES` (`platform=local` does not auto-inject `RENOVATE_TOKEN`).

## Conventions

- **Terragrunt**: put unit inputs (and derived values) in `infra/env.hcl`, one `locals.cluster` / `locals.addons` / `locals.argocd_config` map. A unit's `terragrunt.hcl` only wires `inputs = local.env.locals.<unit>` and carries no values. `apply --all` order is `cluster -> addons -> argocd-config`; `destroy --all` reverses it. Providers resolve the cluster connection from `cluster/artifacts/kubeconfig` via `env.hcl`, so no `KUBECONFIG` export is needed.
- **Secrets**: one SOPS-encrypted file, `infra/secrets.sops.yaml` (recipients in `.sops.yaml`). Edit only via `sops`. The age key is NOT in the repo.
- **ArgoCD**: `platform/` = cluster-scoped/admin resources; `apps/` = regular applications. ApplicationSets generate from `main` with `automated` sync (prune + selfHeal), so pushing to `main` deploys. Adding `apps/<name>/` (or a new `platform/<name>/`) is picked up automatically.
- **Versions**: dependency pins live in `infra/env.hcl` (`talos_version`, `kubernetes_version`, `cilium_chart_version`, `gateway_api_crds_version`), `infra/*/versions.tf` (provider pins), `.github/workflows/pre-commit.yaml` (CLI tools), `.pre-commit-config.yaml`, and ArgoCD `Application` chart `targetRevision`s. Renovate drives bumps, so don't bump versions manually without a reason. When adding/removing a pinned dependency, update `renovate.json` per the [Renovate section](#renovate) and verify with `.github/scripts/test-renovate.py`.

## Rules & guardrails

- **Never** commit, push, or open PRs. The user reviews all changes and runs git operations (add/commit/push/PR) manually.
- **Never** run `terragrunt apply` / `destroy` / `import` against the live cluster unless the user explicitly asks. These are destructive, real-world operations.
- **Never** commit unencrypted secrets, private keys, or Terraform state. `.terraform/`, `.terragrunt-cache/`, `*.tfstate*`, and `artifacts/` are gitignored, so don't force-add them.
- **Never** edit `infra/secrets.sops.yaml` as plaintext or decrypt it into a committed file. Re-encrypt with `sops -e -i` (CI rejects unencrypted `*.sops.yaml`).
- **Never** delete or regenerate machine secrets (`talos_machine_secrets`); the local state and `artifacts/talosconfig` carry cluster identity. Losing them means the cluster can't be re-adopted.
- Don't touch `artifacts/` outputs (kubeconfig/talosconfig); they are generated by the `cluster` unit. `.terragrunt-cache/` is transient, so ignore it.
- Don't modify `.opencode/` (local tooling) unless asked.

## Further reading

- `infra/README.md`: Terragrunt workflow, SOPS/age, unit ordering
- `infra/cluster/README.md`: Talos provisioning, Cilium inline manifest, upgrades, pitfalls
- `infra/addons/README.md`: ArgoCD bootstrap and adding apps
- `infra/argocd-config/README.md`: ApplicationSets
- `~/.config/opencode/plugins/README.md`: multi-session worktree workflow (plan → approve → implement → stop-for-review; worktree-guard plugin, `/new-worktree`, `/plan-approved`, `/finish-pr`)
