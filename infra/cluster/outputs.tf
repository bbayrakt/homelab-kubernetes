output "nodes" {
  description = "Provisioned nodes (IP -> hostname/role/proxmox node)."
  value = {
    for k, v in var.nodes : k => {
      hostname     = v.hostname
      role         = v.role
      proxmox_node = v.proxmox_node
      vm_id        = v.vm_id
    }
  }
}

output "kubeconfig" {
  description = "Path to the cluster kubeconfig file."
  value       = module.talos_cluster.kubeconfig
}

output "talosconfig" {
  description = "Path to the talosctl config file."
  value       = module.talos_cluster.talosconfig
}

output "first_controlplane_ip" {
  description = "IP of the first controlplane node (bootstrap target)."
  value       = module.talos_cluster.first_controlplane_ip
}

output "kubernetes_ca_certificate" {
  description = "Kubernetes API server CA certificate (PEM)."
  value       = module.talos_cluster.kubernetes_ca_certificate
  sensitive   = true
}

output "kubernetes_host" {
  description = "Kubernetes API server endpoint (https://host:6443)."
  value       = module.talos_cluster.kubernetes_host
}
