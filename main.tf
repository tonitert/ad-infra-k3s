terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.51.0"
    }

    tls = {
      source  = "hashicorp/tls"
      version = "4.1.0"
    }

    local = {
      source  = "hashicorp/local"
      version = "2.5.3"
    }

    random = {
      source  = "hashicorp/random"
      version = "3.7.2"
    }

    docker = {
      source  = "kreuzwerker/docker"
      version = "3.6.2"
    }

    null = {
      source  = "hashicorp/null"
      version = "3.2.4"
    }
  }
}

provider "hcloud" {
    token = var.hcloud_token
}

resource "tls_private_key" "ad_server_key" {
    algorithm = "RSA"
    rsa_bits  = 4096
}

resource "hcloud_ssh_key" "ad_server_ssh_key" {
    name       = "ad-server-ssh-key"
    public_key = tls_private_key.ad_server_key.public_key_openssh
}

resource "hcloud_primary_ip" "primary_ip_ad_server" {
    name          = "primary_ip_ad_server"
    datacenter    = "hel1-dc2"
    type          = "ipv4"
    assignee_type = "server"
    auto_delete   = true
}

resource "hcloud_server" "ad_server" {
    name        = "ad-server"
    image       = "debian-12"
    server_type = "cax21"
    location    = "hel1"
    ssh_keys    = [ hcloud_ssh_key.ad_server_ssh_key.id ]

    labels = {
      role = "ad-server"
    }

    public_net {
      ipv4_enabled = true
      ipv4 = hcloud_primary_ip.primary_ip_ad_server.id
      ipv6_enabled = true
    }
}


