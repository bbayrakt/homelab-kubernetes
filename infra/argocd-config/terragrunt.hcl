include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  env = read_terragrunt_config(find_in_parent_folders("env.hcl"))
}

dependencies {
  paths = ["../addons"]
}

# ArgoCD may still be starting right after addons installs it; retry transient
# provider connection failures.
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

inputs = local.env.locals.argocd_config
