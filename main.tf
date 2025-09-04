terraform {
    backend "http" {
      
    }

    required_version = ">= 1.5.0"
    required_providers {
      hcloud = {
        source  = "hetznercloud/hcloud"
        version = ">= 1.51.0"
      }
      cloudflare = {
        source  = "cloudflare/cloudflare"
        version = "~> 5.9"
      }
    }
}