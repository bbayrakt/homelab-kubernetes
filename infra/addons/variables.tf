variable "kubeconfig_path" {
  description = "Path to the cluster kubeconfig (written by infra/terraform to artifacts/kubeconfig)."
  type        = string
  default     = "../terraform/artifacts/kubeconfig"
}

variable "gitops_repo_url" {
  description = "Git (HTTPS) URL of the repo containing the platform/ and apps/ folders ArgoCD syncs."
  type        = string
  default     = "https://github.com/bbayrakt/homelab-kubernetes"
}

variable "github_pat" {
  description = "GitHub PAT for ArgoCD to clone gitops_repo_url. Leave empty if the repo is public."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token (Zone read + DNS edit). Written into cert-manager and external-dns Secrets (DNS-01 / record management)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "argocd_admin_password" {
  description = "PLAINTEXT ArgoCD admin password. Pre-seeded in the argocd-initial-admin-secret (which ArgoCD reads on first start) and used by the argocd provider to authenticate. Held in the shared SOPS secrets file — no bcrypt needed."
  type        = string
  default     = ""
  sensitive   = true
}
