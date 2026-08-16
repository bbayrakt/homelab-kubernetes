variable "nodes" {
  description = "Talos nodes to provision as Proxmox VMs. Key = node IP."
  type = map(object({
    proxmox_node       = string
    hostname           = string
    role               = string
    vm_id              = number
    cores              = number
    memory             = number
    disk_size          = number
    longhorn_disk_size = number
    swap_disk_size     = number
    datastore_id       = string
    cpu_type           = string
    mac_address        = string
    iso_filename       = string
    iso_url            = string
  }))
}

variable "iso_datastore" {
  description = "Datastore that holds the per-node Talos ISOs (e.g. local or a shared CIFS/NFS store)."
  type        = string
}

variable "network_bridge" {
  description = "vSwitch/bridge to attach node NICs to."
  type        = string
}

variable "disk_format" {
  description = "File format for node root disks. LVM-thin (local-lvm) only supports `raw`; use `qcow2` for directory-based storage (snapshots)."
  type        = string
  default     = "raw"
}

variable "disk_ssd" {
  description = "Enable SSD emulation on the root disk (discard/TRIM passthrough, in-guest SSD identification)."
  type        = bool
  default     = true
}

variable "secure_boot" {
  description = "Enroll manufacturers' Secure Boot keys on the OVMF EFI disks. Required when using a Talos secureboot ISO, otherwise the installed UKI can't boot from disk."
  type        = bool
  default     = false
}

variable "enable_guest_agent" {
  description = "Enable the QEMU guest agent on the VMs."
  type        = bool
  default     = false
}
