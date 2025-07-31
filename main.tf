terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "1.51.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "2.5.3"
    }

    random = {
      source  = "hashicorp/random"
      version = "3.7.2"
    }

    null = {
      source  = "hashicorp/null"
      version = "3.2.4"
    }
  }
  backend "http" {
    
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

resource "local_file" "ad_server_ssh_key" {
  content         = tls_private_key.ad_server_key.private_key_pem
  filename        = "${path.module}/keys/ad_server_ssh_key.pem"
  file_permission = "0600"
}

resource "local_file" "ip_address" {
  content         = hcloud_primary_ip.primary_ip_ad_server.ip_address
  filename        = "${path.module}/ip_address.txt"
  file_permission = "0644"
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
  server_type = "cax31"
  location    = "hel1"
  ssh_keys    = [hcloud_ssh_key.ad_server_ssh_key.id]

  labels = {
    role = "ad-server"
  }

  public_net {
    ipv4_enabled = true
    ipv4         = hcloud_primary_ip.primary_ip_ad_server.id
    ipv6_enabled = true
  }
}

resource "local_file" "ansible" {
  content = yamlencode({
    servers = {
      hosts = {
        ad_server = {
          ansible_host                 = hcloud_server.ad_server.ipv4_address
          ansible_user                 = "root"
          ansible_ssh_private_key_file = local_file.ad_server_ssh_key.filename
        }
      }
    }
  })

  filename = "${path.module}/ansible/inventory.yaml"
  provisioner "local-exec" {
    command = <<-EOT
      ANSIBLE_HOST_KEY_CHECKING=False \
      ansible-playbook -i ${local_file.ansible.filename} \
      ansible/pre-server-setup-playbook.yaml
    EOT
  }
}
