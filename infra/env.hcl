# Shared environment configuration: ALL Terragrunt unit inputs are centralized
# here (one local map per unit). Each unit's terragrunt.hcl reads its inputs from
# this single file via read_terragrunt_config(...) and assigns them to `inputs`,
# terragrunt.hcl carries only logic (includes, deps, retries), not values.

locals {
  infra_dir = get_terragrunt_dir()

  gitops_repo_url = "https://github.com/bbayrakt/homelab-kubernetes"

  kubeconfig_path = abspath("${local.infra_dir}/cluster/artifacts/kubeconfig")

  secrets = yamldecode(sops_decrypt_file(abspath("${local.infra_dir}/secrets.sops.yaml")))

  # ---------------------------------------------------------------------------
  # cluster unit inputs
  # ---------------------------------------------------------------------------
  cluster = {
    # Write talosconfig/kubeconfig to the real unit dir (Terragrunt runs from
    # .terragrunt-cache).
    artifacts_dir = abspath("${local.infra_dir}/cluster/artifacts")

    # Proxmox connection
    proxmox_endpoint  = "https://192.168.0.11:8006/"
    proxmox_api_token = local.secrets.proxmox_api_token
    proxmox_username  = ""
    proxmox_password  = ""
    proxmox_insecure  = true

    # Cluster
    cluster_name     = "talos-cluster"
    cluster_endpoint = "https://192.168.0.67:6443"

    # Versions
    talos_version            = "v1.13.8"
    kubernetes_version       = "1.36.3"
    cilium_chart_version     = "1.20.0"
    gateway_api_crds_version = "v1.6.1"

    # Image Factory (standard, non-secureboot metal ISO)
    talos_scheme_id = "e3fab82b561b5e559cdf1c0b1e5950c0e52700b9208a2cfaa5b18454796f3a7e"
    talos_arch      = "amd64"
    talos_iso_name  = "metal-amd64"

    enable_qemu_guest_agent = true

    # Proxmox storage/network defaults
    proxmox_iso_datastore  = "local"
    proxmox_disk_datastore = "local-lvm"
    proxmox_network_bridge = "vmbr0"
    secure_boot            = false

    # Nodes
    nodes = {
      "192.168.0.67" = {
        role         = "controlplane"
        hostname     = "talos-cp-1"
        proxmox_node = "proxmox01"
        vm_id        = 210
        ipv4_address = "192.168.0.67"
        ipv4_prefix  = 24
        ipv4_gateway = "192.168.0.1"
        dns_servers  = ["192.168.0.1"]
        mac_address  = "BC:24:11:00:00:D2"
        cores        = 2
        memory       = 4096
        disk_size    = 40
      }
      "192.168.0.68" = {
        role         = "worker"
        hostname     = "talos-worker-1"
        proxmox_node = "proxmox02"
        vm_id        = 211
        ipv4_address = "192.168.0.68"
        ipv4_prefix  = 24
        ipv4_gateway = "192.168.0.1"
        dns_servers  = ["192.168.0.1"]
        mac_address  = "BC:24:11:00:00:D3"
        cores        = 4
        memory       = 14336
        disk_size    = 80
      }
      "192.168.0.69" = {
        role         = "worker"
        hostname     = "talos-worker-2"
        proxmox_node = "proxmox03"
        vm_id        = 212
        ipv4_address = "192.168.0.69"
        ipv4_prefix  = 24
        ipv4_gateway = "192.168.0.1"
        dns_servers  = ["192.168.0.1"]
        mac_address  = "BC:24:11:00:00:D4"
        cores        = 4
        memory       = 14336
        disk_size    = 80
      }
      "192.168.0.70" = {
        role         = "worker"
        hostname     = "talos-worker-3"
        proxmox_node = "proxmox04"
        vm_id        = 213
        ipv4_address = "192.168.0.70"
        ipv4_prefix  = 24
        ipv4_gateway = "192.168.0.1"
        dns_servers  = ["192.168.0.1"]
        mac_address  = "BC:24:11:00:00:D5"
        cores        = 4
        memory       = 14336
        disk_size    = 80
      }
    }
  }

  # ---------------------------------------------------------------------------
  # addons unit inputs
  # ---------------------------------------------------------------------------
  addons = {
    kubeconfig_path       = local.kubeconfig_path
    gitops_repo_url       = local.gitops_repo_url
    github_pat            = local.secrets.github_pat
    cloudflare_api_token  = local.secrets.cloudflare_api_token
    argocd_admin_password = local.secrets.argocd_admin_password
  }

  # ---------------------------------------------------------------------------
  # argocd-config unit inputs
  # ---------------------------------------------------------------------------
  argocd_config = {
    kubeconfig_path       = local.kubeconfig_path
    gitops_repo_url       = local.gitops_repo_url
    argocd_admin_password = local.secrets.argocd_admin_password
  }
}
