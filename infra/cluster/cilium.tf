# Cilium CNI — rendered locally into a single manifest and embedded as a Talos
# controlplane inline manifest. Talos applies it automatically during bootstrap.
# See https://docs.siderolabs.com/kubernetes-guides/cni/deploying-cilium/
#
# `data.helm_template` renders the chart locally (ClientOnly dry-run, no cluster
# contact), so it works even though the cluster only exists after bootstrap.
data "helm_template" "cilium" {
  name       = "cilium"
  repository = "https://helm.cilium.io/"
  chart      = "cilium"
  version    = var.cilium_chart_version
  namespace  = "kube-system"
  # No cluster/kubeconfig exists at render time, so the provider would report a
  # default Kubernetes version too low for Cilium's kubeVersion constraint. Pin
  # it to the cluster's actual version (used for Capabilities.KubeVersion only).
  kube_version = var.kubernetes_version

  # Cilium's CRDs ship in the chart's crds/ dir, which a plain `helm template`
  # omits; the Talos inline manifest must include them so policies can apply.
  include_crds = true

  # Talos-specific values (Sidero docs, "without kube-proxy" variant):
  #   - ipam.mode=kubernetes (required by Talos)
  #   - kubeProxyReplacement=true + KubePrism (localhost:7445, default on)
  #   - l2announcements.enabled=true (LAN VIP advertisement via ARP)
  #   - gatewayAPI.enabled (Envoy-based Gateway API controller)
  #   - SYS_MODULE deliberately absent (Talos doesn't allow workload module loading)
  #   - cgroup already mounted by Talos (no automount, hostRoot=/sys/fs/cgroup)
  # Note: cluster.proxy.disabled=true is patched into the machine config (module
  # talos-cluster) — kube-proxy is fully replaced by Cilium.
  values = [<<-EOT
    ipam:
      mode: kubernetes
    kubeProxyReplacement: true
    k8sServiceHost: localhost
    k8sServicePort: 7445
    l2announcements:
      enabled: true
    gatewayAPI:
      enabled: true
      enableAlpn: true
      enableAppProtocol: true
    # Leader-election client rate limit for L2 announcement leases
    # (docs sizing: #services / leaseRenewDeadline; homelab small -> 16/32).
    k8sClientRateLimit:
      qps: 16
      burst: 32
    securityContext:
      capabilities:
        ciliumAgent:
          - CHOWN
          - KILL
          - NET_ADMIN
          - NET_RAW
          - IPC_LOCK
          - SYS_ADMIN
          - SYS_RESOURCE
          - DAC_OVERRIDE
          - FOWNER
          - SETGID
          - SETUID
        cleanCiliumState:
          - NET_ADMIN
          - SYS_ADMIN
          - SYS_RESOURCE
    cgroup:
      autoMount:
        enabled: false
      hostRoot: /sys/fs/cgroup
  EOT
  ]
}
