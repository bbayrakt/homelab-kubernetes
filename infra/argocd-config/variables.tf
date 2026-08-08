variable "kubeconfig_path" {
  description = "Path to the cluster kubeconfig, passed from env.hcl."
  type        = string
}

variable "gitops_repo_url" {
  description = "Git (HTTPS) URL of the repo containing the platform/ and apps/ folders ArgoCD syncs."
  type        = string
}

variable "argocd_admin_password" {
  description = "PLAINTEXT ArgoCD admin password used by the argocd provider to authenticate (set on the cluster via the addons unit's initial-admin-secret)."
  type        = string
  sensitive   = true
}
