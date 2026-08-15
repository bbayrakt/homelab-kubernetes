# Homelab Kubernetes

GitOps-driven homelab Kubernetes cluster. A Talos Linux cluster (1 controlplane,
3 workers) runs on Proxmox VE; it is provisioned with Terragrunt + OpenTofu
(`infra/`) and applications are delivered by ArgoCD from this same repo
(`platform/` + `apps/`). Pushing to `main` deploys.

## Stack

| Component                    | Role                                                                 |
|------------------------------|----------------------------------------------------------------------|
| Talos Linux (v1.13.8)        | Immutable OS; machines built from Image Factory schematics (system extensions: intel-ucode, iscsi-tools, util-linux-tools) with static-IP kernel args |
| Kubernetes (1.36.3)          | Cluster on Proxmox VE (4 nodes), LAN 192.168.0.0/24                  |
| Terragrunt + OpenTofu        | Infrastructure provisioning: `cluster -> addons -> argocd-config`     |
| Cilium (1.20.0)              | CNI, kube-proxy-free, L2 LB (LB-IPAM 192.168.0.200-219), Gateway API (Gateway `homelab` at 192.168.0.200), WireGuard encryption, Hubble |
| ArgoCD                       | GitOps delivery: `platform`/`apps` ApplicationSets committed in `argocd/appsets/`, applied by a Terraform-managed bootstrap ApplicationSet; UI at argocd.icaninto.space |
| cert-manager                 | TLS via Let's Encrypt DNS-01 (Cloudflare), ClusterIssuer `letsencrypt-dns01` |
| external-dns                 | Creates/updates Cloudflare DNS records from Gateways/HTTPRoutes      |
| Longhorn                     | Block storage on the worker nodes (dedicated disk labels); UI at longhorn.icaninto.space |
| Grafana Cloud (free tier)    | Metrics (Prometheus remote-write) + logs (Loki), via the `k8s-monitoring` Helm chart; also ingests Talos syslog (port 5140) |
| spegel                       | Peer-to-peer container image distribution between nodes              |
| vCluster                     | Virtual Kubernetes cluster in namespace `vcluster`; access via `vcluster connect` |
| prometheus-operator-crds     | CRDs for the monitoring stack                                        |
| Actions Runner Controller    | Self-hosted GitHub Actions runners in-cluster (ARC), scale set `argocd-diff-runner` |
| PR preview                    | Every PR touching `platform/`/`apps/` gets an Argo CD diff comment **and** a preview deployment into the vCluster (`.github/workflows/pr-preview.yaml`): the diff is rendered by a dedicated Argo CD instance inside the vCluster (`argocd-preview`), changed apps are deployed there with automated sync, and the comment reports Healthy/Degraded per app |
| SOPS + age                   | One encrypted secrets file (`infra/secrets.sops.yaml`), age key never in git |
| VPA (recommendation-only)    | Long-term pod CPU/memory usage history (in-cluster, survives Grafana Cloud's 14-day retention) as the basis for future requests/limits; recommender-only Helm chart, no pod mutation |
| Renovate                     | Automated dependency bumps (versions in `infra/env.hcl`, chart `targetRevision`s, workflows) |

## Repository layout

```
infra/              Terragrunt/OpenTofu units: cluster -> addons -> argocd-config
  env.hcl           ALL unit inputs centralized (versions, nodes, secrets)
  root.hcl          shared remote_state (S3 backend on SeaweedFS, pbkdf2-encrypted)
  secrets.sops.yaml single SOPS-encrypted secrets file (never plaintext)
  cluster/          Talos cluster + Cilium; writes artifacts/kubeconfig + talosconfig
  addons/           Installs ArgoCD, cert-manager, external-dns, ARC namespaces
  argocd-config/    ArgoCD bootstrap ApplicationSet (app-of-appsets)
argocd/appsets/     committed ApplicationSets (platform, apps), applied via the
                    Terraform bootstrap ApplicationSet
platform/           ArgoCD-managed cluster-level resources (network, issuer,
                    metrics-server, kubelet-serving-cert-approver,
                    argocd-diff-runner RBAC, vpa Service/ServiceMonitor + VPA objects)
  helm-charts/      one parent ArgoCD app (app-of-apps) for the Helm chart
                    Applications (cert-manager, external-dns, grafana-cloud,
                    longhorn, prometheus-operator-crds, spegel, vcluster,
                    argocd-diff-preview, gha-runner-scale-set,
                    gha-runner-scale-set-controller, vpa)
apps/               ArgoCD-managed applications (one subdir per app)
.github/            CI workflows + scripts (pre-commit, PR preview with vCluster deploy)
.pre-commit-config.yaml  the single lint/format gate
renovate.json       dependency automation
```

## Resource recommendations (VPA)

`platform/helm-charts/vpa/` installs the VPA recommender from the official
`vertical-pod-autoscaler` Helm chart (updater + admission controller disabled;
`updateMode: Off` everywhere, so no pod is ever mutated or evicted). The chart
app also installs the VPA CRDs (ArgoCD renders charts with
`helm template --include-crds`, so the chart's `crds/` directory is applied).
`platform/vpa/` ships the recommender Service/ServiceMonitor and the VPA
objects per workload. The recommender accumulates long-term CPU/memory
usage history in-cluster (unbounded by Grafana Cloud's 14-day retention) and
exposes recommendations via `kubectl get vpa -A`, so requests/limits can be
set from data instead of guesses. Storage is sized from Grafana Cloud queries
(`kubelet_volume_stats_*`, `longhorn_volume_*`). See
[`platform/vpa/README.md`](platform/vpa/README.md) for reading recommendations,
timelines, and the follow-up workflow.

## PR preview (vCluster)

Every PR touching `platform/**` or `apps/**` runs `.github/workflows/pr-preview.yaml`
on the self-hosted `argocd-diff-runner` scale set:

1. **Diff:** `argocd-diff-preview` renders base vs. target through a dedicated
   Argo CD instance running inside the vCluster (namespace `argocd-preview`).
   The workflow installs that instance itself, idempotently, via
   `helm upgrade --install` (chart `argo-cd` from `argoproj.github.io/argo-helm`).
2. **Deploy:** `.github/scripts/pr-preview.py` maps the changed files to app
   directories and filters them through an allowlist of apps that can run in a
   vCluster (no CRDs, no host infrastructure). Each changed testable app gets
   one ArgoCD `Application` (`preview-pr-<N>-<app>`, source
   `refs/pull/<N>/merge`, automated sync with prune + selfHeal, resources
   finalizer). Everything else is skipped with the reason in the report.
3. **Health:** the script waits (5 min per app) for `Synced` + `Healthy` and
   collects operation errors and pod crash log excerpts on failure.
4. **Report:** one PR comment with the diff plus a per-app table:
   `Healthy` / `Degraded` / `Skipped`. The workflow fails the check when a
   tested app is unhealthy; nothing ever touches the host cluster.

Closing/merging the PR deletes the `preview-pr-<N>-*` Applications (the
resources finalizer prunes the workloads). The vCluster and its Argo CD stay
installed for the next PR.

Testable today: `platform/metrics-server`, `platform/kubelet-serving-cert-approver`.
The allowlist lives in `.github/scripts/pr-preview.py`.

## Getting started

### Prerequisites

- [Terragrunt](https://terragrunt.com/) and [OpenTofu](https://opentofu.org/)
- [talosctl](https://www.talos.dev/) (for cluster unit + day-2 node operations)
- [sops](https://getsops.io/) + [age](https://github.com/FiloSottile/age) with the
  age key at `~/.config/sops/age/keys.txt` (or `SOPS_AGE_KEY_FILE`)
- Proxmox API token (bpg provider; see `infra/cluster/README.md` for required
  permissions)
- Cloudflare API token (DNS-01 certs + external-dns), set in
  `infra/secrets.sops.yaml`
- GitHub PAT (private repo access for ArgoCD) + GitHub OIDC client for ArgoCD
  login, both in `infra/secrets.sops.yaml`

### Bootstrap

```sh
cd infra
terragrunt apply --all    # cluster -> addons (ArgoCD, cert-manager, external-dns) -> argocd-config (bootstrap ApplicationSet)
```

The `argocd-config` unit creates a bootstrap ApplicationSet that applies the
committed `platform`/`apps` ApplicationSets from `argocd/appsets/`. ArgoCD then
syncs `platform/` and `apps/` automatically (automated sync with prune +
selfHeal).

### Day-2 workflows

```sh
cd infra
terragrunt plan --all     # infra changes: nodes, versions, Talos/Cilium config
terragrunt apply --all    # apply them
```

App changes: edit `platform/` or `apps/`, push to `main`. ArgoCD deploys. PRs
touching `platform/` or `apps/` get a diff comment plus a preview deployment
into the vCluster (see [PR preview](#pr-preview-vcluster)).

Secrets: edit `infra/secrets.sops.yaml` with `sops` (re-encrypts on save). The
age key is not in the repo; all units decrypt via `env.hcl`.

Validation: `pre-commit run --all-files` (terragrunt fmt/validate/tflint,
yamllint, kubeconform, argocd-apps-check, detect-secrets, sops-encrypted, ruff,
renovate-config-validator). CI runs the same on push/PR.

## Further reading

- [`infra/README.md`](infra/README.md): Terragrunt workflow, SOPS/age, unit ordering
- [`infra/cluster/README.md`](infra/cluster/README.md): Talos provisioning, Cilium inline manifest, networking, upgrades
- [`infra/addons/README.md`](infra/addons/README.md): ArgoCD bootstrap, adding apps
- [`infra/argocd-config/README.md`](infra/argocd-config/README.md): bootstrap ApplicationSet
- [`AGENTS.md`](AGENTS.md): guidance for AI coding agents working in this repo
