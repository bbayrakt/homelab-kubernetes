resource "talos_machine_secrets" "this" {}

data "talos_machine_configuration" "controlplane" {
  cluster_name       = var.cluster_name
  cluster_endpoint   = var.cluster_endpoint
  machine_type       = "controlplane"
  machine_secrets    = talos_machine_secrets.this.machine_secrets
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
}

data "talos_machine_configuration" "worker" {
  cluster_name       = var.cluster_name
  cluster_endpoint   = var.cluster_endpoint
  machine_type       = "worker"
  machine_secrets    = talos_machine_secrets.this.machine_secrets
  talos_version      = var.talos_version
  kubernetes_version = var.kubernetes_version
}

resource "talos_machine_configuration_apply" "this" {
  for_each                    = var.nodes
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = each.value.role == "controlplane" ? data.talos_machine_configuration.controlplane.machine_configuration : data.talos_machine_configuration.worker.machine_configuration
  node                        = each.key
  config_patches = concat(
    [
      templatefile("${path.module}/templates/node-config.yaml.tmpl", {
        hostname       = each.value.hostname
        install_disk   = each.value.install_disk
        install_img    = var.talos_installer
        ip_address     = format("%s/%d", each.value.ipv4_address, each.value.ipv4_prefix)
        gateway        = each.value.ipv4_gateway
        dns_servers    = each.value.dns_servers
        interface_name = each.value.mac_address != "" ? format("enx%s", lower(replace(each.value.mac_address, ":", ""))) : "eth0"
        node_labels    = each.value.node_labels
        node_taints    = each.value.node_taints
      })
    ],
    # Disable Talos's built-in CNI (Flannel) so Cilium (installed as an inline
    # manifest below) is the only CNI, and disable kube-proxy: Cilium runs with
    # kubeProxyReplacement=true (required for L2 announcements). All nodes.
    [
      yamlencode({
        cluster = {
          network = {
            cni = { name = "none" }
          }
          proxy = {
            disabled = true
          }
        }
      })
    ],
    # Controlplane-only inline manifests, applied in order:
    #  1. Gateway API CRDs — must exist before the Cilium gateway controller
    #     starts (Cilium 1.20 requires Gateway API v1.6.1 CRDs).
    #  2. Cilium (with kube-proxy replacement, L2 announcements, Gateway API).
    # Identical content on every controlplane (per the Sidero docs).
    each.value.role == "controlplane" ? [
      yamlencode({
        cluster = {
          inlineManifests = [
            { name = "gateway-api-crds", contents = var.gateway_api_inline_manifest },
            { name = "cilium", contents = var.cilium_inline_manifest },
          ]
        }
      })
    ] : []
  )
}

locals {
  controlplane_ips    = [for k, v in var.nodes : k if v.role == "controlplane"]
  first_controlplane_ip = local.controlplane_ips[0]
}

resource "talos_machine_bootstrap" "this" {
  depends_on = [talos_machine_configuration_apply.this]

  client_configuration = talos_machine_secrets.this.client_configuration
  node                 = local.first_controlplane_ip
}

data "talos_client_configuration" "this" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.this.client_configuration
  nodes                = keys(var.nodes)
  endpoints = local.controlplane_ips
}

resource "talos_cluster_kubeconfig" "this" {
  depends_on = [talos_machine_bootstrap.this]

  client_configuration = talos_machine_secrets.this.client_configuration
  node                 = local.first_controlplane_ip
}
