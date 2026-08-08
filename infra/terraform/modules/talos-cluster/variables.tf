variable "cluster_name" {
  description = "Name of the Talos/Kubernetes cluster."
  type        = string
}

variable "cluster_endpoint" {
  description = "Kubernetes API server endpoint, e.g. https://10.0.0.10:6443. Should be a stable IP (VIP or first controlplane)."
  type        = string
}

variable "talos_version" {
  description = "Talos Linux version contract for generated machine configs."
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes component image versions baked into machine configs."
  type        = string
}

variable "talos_installer" {
  description = "Full installer container image (scheme + version) written into machine.install.image."
  type        = string
}

variable "nodes" {
  description = "Talos nodes. Key = node IP / talosctl address."
  type = map(object({
    role         = string
    hostname     = string
    install_disk = string
    ipv4_address = string
    ipv4_prefix  = number
    ipv4_gateway = string
    dns_servers  = list(string)
    mac_address  = string
    node_labels  = map(string)
    node_taints  = list(string)
  }))
}

variable "artifacts_dir" {
  description = "Directory to write generated talosconfig/kubeconfig artifacts to."
  type        = string
  default     = "artifacts"
}
