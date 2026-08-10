#!/usr/bin/env bash
# Rolling reboot of all cluster nodes: drain -> reboot -> wait Ready -> uncordon.
# Workers are rebooted first, control planes last (a single control plane means
# a brief control-plane outage, so it goes last).
#
# Usage: ./rolling-reboot.sh [--dry-run] [--yes]
#   --dry-run  print the commands without running them
#   --yes/-y   skip the confirmation prompt
#
# Requires kubectl + talosctl. KUBECONFIG/TALOSCONFIG default to the cluster
# unit artifacts (infra/cluster/artifacts).
set -euo pipefail

DRY_RUN=0
ASSUME_YES=0

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
  shift
done

for cmd in kubectl talosctl; do
  command -v "$cmd" >/dev/null || { echo "error: $cmd not found in PATH" >&2; exit 1; }
done

repo_root="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
export KUBECONFIG="${KUBECONFIG:-${repo_root}/infra/cluster/artifacts/kubeconfig}"
export TALOSCONFIG="${TALOSCONFIG:-${repo_root}/infra/cluster/artifacts/talosconfig}"

[[ -f $KUBECONFIG ]] || { echo "error: kubeconfig not found: $KUBECONFIG" >&2; exit 1; }
[[ -f $TALOSCONFIG ]] || { echo "error: talosconfig not found: $TALOSCONFIG" >&2; exit 1; }

run() {
  if (( DRY_RUN )); then
    printf 'dry-run: %s\n' "$*"
  else
    printf '>>> %s\n' "$*"
    "$@"
  fi
}

node_ip() {
  kubectl get node "$1" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
}

wait_ready() {
  local name=$1 tries=$2
  if (( DRY_RUN )); then
    printf 'dry-run: wait for node/%s Ready\n' "$name"
    return 0
  fi
  local status
  while (( tries-- )); do
    status="$(kubectl get node "$name" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
    if [[ $status == "True" ]]; then
      echo "==> [$name] Ready"
      return 0
    fi
    sleep 5
  done
  echo "!! [$name] not Ready after timeout" >&2
  return 1
}

verify_swap() {
  local name=$1 ip=$2 tries=10
  if (( DRY_RUN )); then
    printf 'dry-run: talosctl -n %s get swap; get zswapstatus\n' "$ip"
    return 0
  fi
  while (( tries-- )); do
    if talosctl -n "$ip" get swap 2>/dev/null | grep -q SwapStatus &&
       talosctl -n "$ip" get zswapstatus 2>/dev/null | grep -q ZswapStatus; then
      echo "==> [$name] swap + zswap active"
      return 0
    fi
    sleep 3
  done
  echo "!! [$name] swap/zswap not detected yet (check with: talosctl -n $ip get swap)" >&2
  return 1
}

roll_node() {
  local name=$1 ip=$2
  echo
  echo "==> [$name] ($ip): draining"
  run kubectl drain "$name" --ignore-daemonsets --delete-emptydir-data --timeout=300s
  echo "==> [$name] ($ip): rebooting"
  run talosctl -n "$ip" reboot --timeout=10m
  echo "==> [$name] ($ip): waiting for Ready"
  wait_ready "$name" 60
  echo "==> [$name] ($ip): uncordoning"
  run kubectl uncordon "$name"
  verify_swap "$name" "$ip" || true
}

read -ra all_nodes <<< "$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')"
read -ra cp_nodes <<< "$(kubectl get nodes -l 'node-role.kubernetes.io/control-plane' -o jsonpath='{.items[*].metadata.name}')"

if [[ ${#all_nodes[@]} -eq 0 ]]; then
  echo "error: no nodes found in the cluster" >&2
  exit 1
fi

if [[ ${#cp_nodes[@]} -eq 0 ]]; then
  echo "error: no control-plane nodes found (label node-role.kubernetes.io/control-plane)" >&2
  exit 1
fi

workers=()
for n in "${all_nodes[@]}"; do
  is_cp=0
  for c in "${cp_nodes[@]}"; do
    [[ $n == "$c" ]] && { is_cp=1; break; }
  done
  (( is_cp )) || workers+=("$n")
done

echo "Control planes: ${cp_nodes[*]}"
echo "Workers:        ${workers[*]:-none}"
echo

if (( ! ASSUME_YES && ! DRY_RUN )); then
  read -rp "Reboot these nodes? [y/N] " ans
  [[ ${ans,,} == "y" ]] || { echo "aborted"; exit 1; }
fi

for w in "${workers[@]}"; do
  roll_node "$w" "$(node_ip "$w")"
done

for c in "${cp_nodes[@]}"; do
  roll_node "$c" "$(node_ip "$c")"
done

echo
echo "All nodes rebooted."
