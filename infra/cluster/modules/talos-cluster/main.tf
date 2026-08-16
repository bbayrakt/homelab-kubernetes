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
        install_img    = each.value.install_img
        ip_address     = format("%s/%d", each.value.ipv4_address, each.value.ipv4_prefix)
        gateway        = each.value.ipv4_gateway
        dns_servers    = each.value.dns_servers
        interface_name = each.value.mac_address != "" ? format("enx%s", lower(replace(each.value.mac_address, ":", ""))) : "eth0"
        node_labels    = each.value.node_labels
        node_taints    = each.value.node_taints
      })
    ],
    # Stream Talos service logs (machined, apid, containerd, kubelet, kernel,
    # ...) as json_lines over TCP to the node's own IP, where the
    # k8s-monitoring Alloy DaemonSet listens (hostNetwork).
    # https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/logging-and-telemetry/logging
    var.talos_log_enabled ? [
      yamlencode({
        machine = {
          logging = {
            destinations = [
              {
                endpoint  = "tcp://${each.value.ipv4_address}:${var.talos_log_port}/"
                format    = "json_lines"
                extraTags = { node = each.value.hostname }
              }
            ]
          }
        }
      })
    ] : [],
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
    # Kubelet serving-cert rotation so kubelets get CA-signed serving certs
    # (no --kubelet-insecure-tls for metrics-server):
    # https://docs.siderolabs.com/kubernetes-guides/monitoring-and-observability/deploy-metrics-server
    [
      yamlencode({
        machine = {
          kubelet = {
            extraArgs = {
              "rotate-server-certificates" = "true"
            }
          }
        }
      })
    ],
    # Spegel P2P image mirroring: retain unpacked layers so nodes can serve
    # images to peers.
    # https://docs.siderolabs.com/kubernetes-guides/advanced-guides/spegel
    [
      yamlencode({
        machine = {
          files = [
            {
              path    = "/etc/cri/conf.d/20-customization.part"
              op      = "create"
              content = "[plugins.\"io.containerd.cri.v1.images\"]\n  discard_unpacked_layers = false\n"
            }
          ]
        }
      })
    ],
    # Encrypted swap device on the dedicated scsi2 disk (entire disk is used as
    # swap — no minSize/maxSize) + zswap compressed swap cache, on all nodes.
    # https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/swap
    [
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "SwapVolumeConfig"
        name       = "swap"
        provisioning = {
          diskSelector = {
            match = "'/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi2' in disk.symlinks"
          }
          # minSize only: maxSize unset => Talos grows the partition to fill the
          # entire disk (no leftover space). minSize acts as a floor.
          minSize = "3GiB"
        }
        encryption = {
          provider = "luks2"
          keys = [
            {
              # nodeID: key derived from node UUID + partition label. TPM keys
              # require a Secure Boot UKI (pcrpkey in /.extra), which this
              # non-secureboot cluster doesn't have.
              slot   = 0
              nodeID = {}
            }
          ]
        }
      })
    ],
    [
      yamlencode({
        apiVersion      = "v1alpha1"
        kind            = "ZswapConfig"
        maxPoolPercent  = 20
        shrinkerEnabled = true
      })
    ],
    # Let the kubelet use swap:
    # https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/swap#kubernetes-and-swap
    [
      yamlencode({
        machine = {
          kubelet = {
            extraConfig = {
              memorySwap = {
                swapBehavior = "LimitedSwap"
              }
            }
          }
        }
      })
    ],
    # Worker-only Longhorn storage disk: Talos carves the dedicated scsi1
    # disk into a volume mounted at /var/mnt/longhorn (the UserVolumeConfig
    # data path the Longhorn Helm chart uses as its default).
    # https://docs.siderolabs.com/kubernetes-guides/csi/longhorn
    each.value.role == "worker" ? [
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "UserVolumeConfig"
        name       = "longhorn"
        volumeType = "disk"
        provisioning = {
          diskSelector = {
            match = "'/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi1' in disk.symlinks"
          }
        }
      })
    ] : [],
    # Controlplane-only inline manifests, applied in order:
    #  1. Gateway API CRDs — must exist before the Cilium gateway controller
    #     starts (Cilium 1.20 requires Gateway API v1.6.1 CRDs).
    #  2. Cilium (with kube-proxy replacement, L2 announcements, Gateway API).
    # Identical content on every controlplane (per the Sidero docs).
    each.value.role == "controlplane" ? [
      yamlencode({
        cluster = {
          # Expose the etcd metrics endpoint for monitoring scrapes:
          # https://docs.siderolabs.com/kubernetes-guides/monitoring-and-observability/etcd-metrics
          etcd = {
            extraArgs = {
              "listen-metrics-urls" = "http://0.0.0.0:2381"
            }
          }
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
  controlplane_ips      = [for k, v in var.nodes : k if v.role == "controlplane"]
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
  endpoints            = local.controlplane_ips
}

resource "talos_cluster_kubeconfig" "this" {
  depends_on = [talos_machine_bootstrap.this]

  client_configuration = talos_machine_secrets.this.client_configuration
  node                 = local.first_controlplane_ip
}
