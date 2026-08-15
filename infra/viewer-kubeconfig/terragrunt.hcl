include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  env = read_terragrunt_config(find_in_parent_folders("env.hcl"))
}

dependencies {
  paths = ["../cluster"]
}

dependency "cluster" {
  config_path = "../cluster"
}

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

inputs = merge(
  local.env.locals.viewer_kubeconfig,
  {
    kubernetes_ca_certificate = try(dependency.cluster.outputs.kubernetes_ca_certificate, "")
    kubernetes_host           = try(dependency.cluster.outputs.kubernetes_host, "")
  }
)
