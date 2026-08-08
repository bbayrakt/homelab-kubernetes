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
  config_patches = [
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
  ]
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
