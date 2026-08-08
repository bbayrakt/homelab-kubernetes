output "vm_ids" {
  description = "Map of node IP -> Proxmox VM ID."
  value       = { for k, v in proxmox_virtual_environment_vm.node : k => v.vm_id }
}
