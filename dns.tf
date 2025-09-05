variable "cloudflare_token" {
  description = "Cloudflare API token"
  type        = string
  sensitive   = true
}

provider "cloudflare" {
  api_token = var.cloudflare_token
}

resource "cloudflare_dns_record" "ctfnote" {
  count   = length(module.kube-hetzner.control_planes_public_ipv4)
  zone_id = data.cloudflare_zone.tertsonen_xyz.zone_id
  name    = "ctfnote.ad"
  type    = "A"
  content = module.kube-hetzner.control_planes_public_ipv4[count.index]
  ttl     = 1
  proxied = false
}

data "cloudflare_zone" "tertsonen_xyz" {
  filter = {
    name = "tertsonen.xyz"
  }
}