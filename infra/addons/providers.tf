# These providers talk to the Kubernetes API, so this root must only be run /
# planned against a LIVE cluster (after infra/cluster has bootstrapped it and
# written artifacts/kubeconfig). See README for the apply order.
provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig_path
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}
