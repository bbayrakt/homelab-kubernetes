terraform {
  required_version = ">= 1.7"

  required_providers {
    argocd = {
      source  = "registry.terraform.io/oboukili/argocd"
      version = "~> 6.0"
    }
  }
}
