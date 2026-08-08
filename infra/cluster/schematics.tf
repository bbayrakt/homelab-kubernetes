resource "talos_image_factory_schematic" "node" {
  for_each = var.nodes

  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = local.talos_system_extensions
      }
      extraKernelArgs = [
        format("ip=%s::%s:%d:%s:%s:off:%s",
          each.value.ipv4_address,
          each.value.ipv4_gateway,
          each.value.ipv4_prefix,
          each.value.hostname,
          var.talos_maintenance_device,
          try(each.value.dns_servers[0], ""),
        ),
        # console on the serial device so maintenance/install logs are visible
        # via `qm terminal <vmid>` on the Proxmox host.
        "console=ttyS0",
      ]
    }
  })
}
