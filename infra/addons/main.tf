###
# ArgoCD
###

resource "terraform_data" "argocd_admin_password_bcrypt" {
  input = bcrypt(var.argocd_admin_password)

  lifecycle {
    ignore_changes = [input]
  }
}

resource "helm_release" "argo_cd" {
  name             = "argo-cd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.3.0"
  namespace        = "argocd"
  create_namespace = true
  wait             = true

  values = [
    yamlencode({
      server = {
        service = { type = "ClusterIP" }
        ingress = { enabled = false }
      }
      applicationSet = { enabled = true }
      configs = {
        params = {
          "server.insecure" = true
        }
        secret = {
          createSecret                   = true
          # Stable hash from state
          argocdServerAdminPassword      = terraform_data.argocd_admin_password_bcrypt.output
          argocdServerAdminPasswordMtime = "2026-08-08T00:00:00Z"
        }
        repositories = var.github_pat != "" ? [
          {
            name     = "homelab-kubernetes"
            url      = var.gitops_repo_url
            username = "git"
            password = var.github_pat
          }
        ] : []
      }
    })
  ]
}

###
# Cert-Manager
###

resource "kubernetes_namespace_v1" "cert_manager" {
  metadata { name = "cert-manager" }
}

resource "kubernetes_secret_v1" "cert_manager_cloudflare" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = kubernetes_namespace_v1.cert_manager.metadata[0].name
  }
  data = {
    "cloudflare-api-token" = var.cloudflare_api_token
  }
}

###
# External-DNS
###

resource "kubernetes_namespace_v1" "external_dns" {
  metadata { name = "external-dns" }
}

resource "kubernetes_secret_v1" "external_dns_cloudflare" {
  metadata {
    name      = "cloudflare-api-token"
    namespace = kubernetes_namespace_v1.external_dns.metadata[0].name
  }
  data = {
    "cloudflare-api-token" = var.cloudflare_api_token
  }
}
