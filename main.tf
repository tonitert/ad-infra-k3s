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

resource "null_resource" "ad_server_docker_setup" {
    depends_on = [hcloud_server.ad_server, hcloud_firewall.server_firewall]

    provisioner "remote-exec" {
      inline = [
        "sudo apt-get update",
        "sudo apt-get install -y ca-certificates curl",
        "sudo install -m 0755 -d /etc/apt/keyrings",
        "sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc",
        "sudo chmod a+r /etc/apt/keyrings/docker.asc",
        "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null",
        "sudo apt-get update",
        "sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin dbus-user-session uidmap slirp4netns docker-ce-rootless-extras",
        "adduser containers --system",
        "su containers -s /bin/bash -c 'dockerd-rootless-setuptool.sh install'",
      ]
      connection {
        type = "ssh"
        user = "root"
        host = hcloud_server.ad_server.ipv4_address
        private_key = tls_private_key.ad_server_key.private_key_pem
      }
    }
}

output "ad_server_id" {
    value = hcloud_server.ad_server.id
}

resource "hcloud_firewall" "server_firewall" {
  name = "nginx-firewall"
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = ["0.0.0.0/0"]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = ["0.0.0.0/0"]
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = ["0.0.0.0/0"]
  }
}

resource "local_file" "ad_server_private_key" {
    content  = tls_private_key.ad_server_key.private_key_pem
    filename = "${path.module}/keys/ad-server-private-key.pem"
    file_permission = "0600"
}

