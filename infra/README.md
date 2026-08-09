# Infra (Terragrunt)

Terragrunt orchestrates the separate Terraform/OpenTofu projects (units) in this
directory. `apply --all` runs them in dependency order: `cluster → addons →
argocd-config`.

| Unit            | Purpose                                                                  |
|-----------------|--------------------------------------------------------------------------|
| `cluster`       | Talos cluster + Cilium (kube-proxy-free, L2 LB, Gateway API CRDs)        |
| `addons`        | Installs ArgoCD, Cert Manager and ExternalDNS to bootstrap ArgoCD        |
| `argocd-config` | Configures ArgoCD resources (ApplicationSets) — runs after ArgoCD exists |

Run everything with one command from this directory:

```sh
terragrunt apply --all --provider-cache  # or: plan, validate, destroy
```

`apply --all` runs `cluster` first, then `addons` (ArgoCD), then `argocd-config`
(once ArgoCD is up); `destroy --all` reverses that. Keeping the ApplicationSets
in `argocd-config` (not `addons`) means a from-scratch apply never tries to use
the argocd provider before ArgoCD exists.

## Tooling

- [**Terragrunt**](https://terragrunt.com/)
- [**OpenTofu**](https://opentofu.org/) (or [Terraform](https://developer.hashicorp.com/terraform))
- [**SOPS**](https://getsops.io/) + [**age**](https://github.com/FiloSottile/age) for committing secrets

## Layout

```
infra/
  root.hcl            # shared remote_state (local, per-unit real dir)
  env.hcl             # ALL unit inputs + shared values (secrets decrypt, kubeconfig)
  secrets.sops.yaml   # single SOPS-encrypted secrets file (all units)
  cluster/            # unit: cluster terraform root (main.tf, ... modules/)
    terragrunt.hcl    # logic only: inputs = local.env.locals.cluster
  addons/             # unit: ArgoCD install + prerequisite namespaces/secrets
    terragrunt.hcl    # logic only: inputs = local.env.locals.addons
  argocd-config/      # unit: ArgoCD ApplicationSets (argocd provider)
    terragrunt.hcl    # logic only: inputs = local.env.locals.argocd_config
```

## Secrets (SOPS + AGE)

- One encrypted file for all units: `infra/secrets.sops.yaml`.
  (`.sops.yaml` at the repo root holds the recipients / creation rules.)
- The **private** AGE key is NOT in git: it lives at
  `~/.config/sops/age/keys.txt` (override with `SOPS_AGE_KEY_FILE`).

Edit/decrypt:

```sh
cd infra
sops secrets.sops.yaml           # open in $EDITOR, re-encrypts on save
sops --decrypt secrets.sops.yaml
```

Terragrunt resolves all inputs (and decrypts secrets) via `infra/env.hcl`, which
each unit's `terragrunt.hcl` reads with `read_terragrunt_config(...)`.

## Typical workflows

```sh
cd infra
terragrunt validate --all   # dry config check
terragrunt plan --all       # plan all units
terragrunt apply --all      # apply all
terragrunt destroy --all    # tear down all
```

No `KUBECONFIG` export is needed, as the `addons`/`argocd-config` providers resolve
the cluster connection from the kubeconfig the `cluster` unit writes
(`cluster/artifacts/kubeconfig`) via `env.hcl`'s `kubeconfig_path`.

To operate on a single unit:

```sh
cd infra/cluster        && terragrunt apply
cd infra/addons         && terragrunt apply
cd infra/argocd-config  && terragrunt apply
```
