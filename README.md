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
| ArgoCD                       | GitOps delivery via ApplicationSets (`platform/`, `apps/`); UI at argocd.icaninto.space |
| cert-manager                 | TLS via Let's Encrypt DNS-01 (Cloudflare), ClusterIssuer `letsencrypt-dns01` |
| external-dns                 | Creates/updates Cloudflare DNS records from Gateways/HTTPRoutes      |
| Longhorn                     | Block storage on the worker nodes (dedicated disk labels); UI at longhorn.icaninto.space |
| Grafana Cloud (free tier)    | Metrics (Prometheus remote-write) + logs (Loki), via the `k8s-monitoring` Helm chart; also ingests Talos syslog (port 5140) |
| spegel                       | Peer-to-peer container image distribution between nodes              |
| prometheus-operator-crds     | CRDs for the monitoring stack                                        |
| SOPS + age                   | One encrypted secrets file (`infra/secrets.sops.yaml`), age key never in git |
| Renovate                     | Automated dependency bumps (versions in `infra/env.hcl`, chart `targetRevision`s, workflows) |

## Repository layout

```
infra/              Terragrunt/OpenTofu units: cluster -> addons -> argocd-config
  env.hcl           ALL unit inputs centralized (versions, nodes, secrets)
  root.hcl          shared remote_state (S3 backend on SeaweedFS, pbkdf2-encrypted)
  secrets.sops.yaml single SOPS-encrypted secrets file (never plaintext)
  cluster/          Talos cluster + Cilium; writes artifacts/kubeconfig + talosconfig
  addons/           Installs ArgoCD, cert-manager, external-dns
  argocd-config/    ArgoCD ApplicationSets (platform, apps)
platform/           ArgoCD-managed cluster-level resources (network, issuer,
                    metrics-server, kubelet-serving-cert-approver)
  helm-charts/      one parent ArgoCD app (app-of-apps) for the Helm chart
                    Applications (cert-manager, external-dns, grafana-cloud,
                    longhorn, prometheus-operator-crds, spegel)
apps/               ArgoCD-managed applications (one subdir per app)
.github/            pre-commit CI workflow + scripts
.pre-commit-config.yaml  the single lint/format gate
renovate.json       dependency automation
```

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
terragrunt apply --all    # cluster -> addons (ArgoCD, cert-manager, external-dns) -> argocd-config (ApplicationSets)
```

Once the ApplicationSets exist, ArgoCD syncs `platform/` and `apps/`
automatically (automated sync with prune + selfHeal).

### Day-2 workflows

```sh
cd infra
terragrunt plan --all     # infra changes: nodes, versions, Talos/Cilium config
terragrunt apply --all    # apply them
```

App changes: edit `platform/` or `apps/`, push to `main`. ArgoCD deploys.

Secrets: edit `infra/secrets.sops.yaml` with `sops` (re-encrypts on save). The
age key is not in the repo; all units decrypt via `env.hcl`.

Validation: `pre-commit run --all-files` (terragrunt fmt/validate/tflint,
yamllint, kubeconform, argocd-apps-check, detect-secrets, sops-encrypted, ruff,
renovate-config-validator). CI runs the same on push/PR.

## Further reading

- [`infra/README.md`](infra/README.md): Terragrunt workflow, SOPS/age, unit ordering
- [`infra/cluster/README.md`](infra/cluster/README.md): Talos provisioning, Cilium inline manifest, networking, upgrades
- [`infra/addons/README.md`](infra/addons/README.md): ArgoCD bootstrap, adding apps
- [`infra/argocd-config/README.md`](infra/argocd-config/README.md): ApplicationSets
- [`AGENTS.md`](AGENTS.md): guidance for AI coding agents working in this repo
