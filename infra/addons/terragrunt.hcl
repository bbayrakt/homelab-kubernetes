# Terragrunt unit: the ArgoCD GitOps bootstrap (cluster must exist first — see
# `dependencies` below for run-all ordering). Runs terraform in-place.
#
# Secret inputs (github_pat, cloudflare_api_token, argocd admin bcrypt) come
# from the shared SOPS-encrypted ../secrets.sops.yaml.
include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  env = read_terragrunt_config(find_in_parent_folders("env.hcl"))
}

# Apply-all runs cluster first; destroy-all tears this down first.
dependencies {
  paths = ["../cluster"]
}

# `dependencies` only guarantees ordering, not readiness: right after cluster
# bootstrap the controlplane reboots into its cluster config, so the Kubernetes
# API endpoint can be momentarily unreachable. Retry the whole apply until the
# endpoint accepts connections (the helm/kubernetes providers surface this as a
# "connection refused"/"cluster unreachable" error).
errors {
  retry "cluster_not_ready" {
    retryable_errors = [
      ".*connection refused.*",
      ".*Kubernetes cluster unreachable.*",
      ".*dial tcp .*: connect.*",
      ".*connection reset by peer.*",
      ".*failed to execute.*kubeconfig.*",
      ".*failed to create new session client.*",
      ".*failed to connect.*argocd.*",
      ".*Get \\\"https://.*connection refused.*",
    ]
    max_attempts       = 20
    sleep_interval_sec = 30
  }
}

inputs = {
  # Shared values sourced from env.hcl (repo URL, kubeconfig path, secrets).
  kubeconfig_path       = local.env.locals.kubeconfig_path
  gitops_repo_url       = local.env.locals.gitops_repo_url
  github_pat            = local.env.locals.secrets.github_pat
  cloudflare_api_token  = local.env.locals.secrets.cloudflare_api_token
  argocd_admin_password = local.env.locals.secrets.argocd_admin_password
}
