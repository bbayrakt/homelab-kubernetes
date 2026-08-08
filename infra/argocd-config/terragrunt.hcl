include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  env = read_terragrunt_config(find_in_parent_folders("env.hcl"))
}

dependencies {
  paths = ["../addons"]
}

errors {
  retry "argo_not_ready" {
    retryable_errors = [
      ".*connection refused.*",
      ".*Kubernetes cluster unreachable.*",
      ".*dial tcp .*: connect.*",
      ".*failed to create new session.*",
      ".*Invalid username or password.*",
    ]
    max_attempts       = 20
    sleep_interval_sec = 30
  }
}

inputs = {
  kubeconfig_path       = local.env.locals.kubeconfig_path
  gitops_repo_url       = local.env.locals.gitops_repo_url
  argocd_admin_password = local.env.locals.secrets.argocd_admin_password
}
