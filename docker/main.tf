terraform {
    required_providers {
        docker = {
            source  = "kreuzwerker/docker"
            version = "3.6.2"
        }

        random = {
            source  = "hashicorp/random"
            version = "3.7.2"
        }
    }
}

data "terraform_remote_state" "hcloud" {
  backend = "local"
  config = {
    path = "../hcloud/terraform.tfstate"
  }
}

provider "docker" {
  host = "ssh://debian@${data.terraform_remote_state.hcloud.outputs.ad_server_id}:22"
  ssh_opts = [
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "StrictHostKeyChecking=no",
    "-i", data.terraform_remote_state.hcloud.outputs.ad_server_private_key.filename
  ]
}

resource "null_resource" "docker_host" {
    triggers = {
      docker_host = "data.terraform_remote_state.hcloud.outputs.ad_server"
    }

    provisioner "file" {
        source      = "${path.module}/files/nginx"
        destination = "/opt/nginx/"
        connection {
          type = "ssh"
          user = "debian"
          host = hcloud_server.ad_server.ipv4_address
          private_key = tls_private_key.ad_server_key.private_key_pem
        }
    }   
}

resource "random_password" "ctfnote_db_password" {
  length  = 16
  special = true
}

resource "random_password" "ctfnote_db_user_password" {
  length  = 16
  special = true
}

resource "docker_image" "ctfnote_api" {
  name = "ghcr.io/tfns/ctfnote/api:latest"
}

resource "docker_network" "internal" {
  name = "internal"
}

resource "docker_volume" "ctfnote_db" {
  name = "ctfnote"
}

resource "docker_volume" "ctfnote_uploads" {
  name = "ctfnote-uploads"
}

resource "docker_volume" "pad_uploads" {
  name = "pad-uploads"
}

resource "docker_image" "ctfnote_db" {
  name = "ghcr.io/tfns/ctfnote/db:latest"
}

resource "docker_image" "ctfnote_front" {
  name = "ghcr.io/tfns/ctfnote/front:latest"
}

resource "docker_image" "hedgedoc" {
  name = "quay.io/hedgedoc/hedgedoc:1.10.3"
}

resource "docker_container" "ctfnote-db" {
  name  = "ctfnote-db"
  image = docker_image.ctfnote_db.id
  restart = "unless-stopped"
  env = [
    "POSTGRES_PASSWORD=${random_password.ctfnote_db_password.result}",
    "POSTGRES_USER=ctfnote",
    "POSTGRES_MULTIPLE_DATABASES=hedgedoc"
  ]
  volumes {
    volume_name    = docker_volume.ctfnote_db.name
    container_path = "/var/lib/postgresql/data"
  }
  networks_advanced {
    name = docker_network.internal.name
  }
}

resource "docker_container" "hedgedoc" {
  name  = "hedgedoc"
  image = docker_image.hedgedoc.id
  restart = "unless-stopped"
  env = [
    "CMD_DB_URL=postgres://ctfnote:${random_password.ctfnote_db_password.result}@db:5432/hedgedoc",
    "CMD_URL_PATH=pad",
    "CMD_DOMAIN",
    "CMD_PROTOCOL_USESSL",
    "CMD_RATE_LIMIT_NEW_NOTES=0",
    "CMD_CSP_ENABLE=false",
    "CMD_IMAGE_UPLOAD_TYPE=filesystem",
    "CMD_DOCUMENT_MAX_LENGTH=-100000"
  ]
  depends_on = [
    docker_container.ctfnote-db
  ]
  volumes {
    volume_name    = docker_volume.pad_uploads.name
    container_path = "/hedgedoc/public/uploads"
  }
  networks_advanced {
    name = docker_network.internal.name
  }
}

resource "docker_container" "ctfnote-front" {
  name  = "ctfnote-front"
  image = docker_image.ctfnote_front.id
  restart = "unless-stopped"
  depends_on = [
    docker_container.hedgedoc
  ]
  networks_advanced {
    name = docker_network.internal.name
  }
}

resource "docker_container" "ctfnote-api" {
  image = docker_image.ctfnote_api.id
  name = "ctfnote-api"
  restart = "unless-stopped"
  env = [
    "PAD_CREATE_URL=http://hedgedoc:3000/new",
    "PAD_SHOW_URL=/",
    "DB_DATABASE=ctfnote",
    "DB_ADMIN_LOGIN=ctfnote",
    "DB_ADMIN_PASSWORD=${random_password.ctfnote_db_password.result}",
    "DB_USER_LOGIN=user_postgraphile",
    "DB_USER_PASSWORD=${random_password.ctfnote_db_user_password.result}",
    "DB_HOST=db",
    "DB_PORT=5432",
    "WEB_PORT=3000",
    "CMD_DOMAIN",
    "CMD_PROTOCOL_USESSL=false",
    "CMD_DOCUMENT_MAX_LENGTH=100000",
    "USE_DISCORD=false",
    "DISCORD_BOT_TOKEN=bot_token",
    "DISCORD_SERVER_ID=server_id",
    "DISCORD_VOICE_CHANNELS=3",
    "DISCORD_REGISTRATION_ENABLED=false",
    "DISCORD_REGISTRATION_CTFNOTE_ROLE",
    "DISCORD_REGISTRATION_ROLE_ID",
    "TZ=UTC",
    "LC_ALL=en_US.UTF-8",
    "SESSION_SECRET="
  ]
  depends_on = [
    docker_container.ctfnote-db
  ]
  volumes {
    volume_name    = docker_volume.ctfnote_uploads.name
    container_path = "/app/uploads"
  }
  networks_advanced {
    name = docker_network.internal.name
  }
}

resource "docker_image" "nginx" {
  name = "nginx:1.29.0"
}

resource "docker_container" "nginx" {
  name  = "nginx"
  image = docker_image.nginx.id
  restart = "unless-stopped"
  ports {
    internal = 80
    external = 80
    ip       = "0.0.0.0"
  }
  ports {
    internal = 443
    external = 443
    ip       = "0.0.0.0"
  }
  networks_advanced {
    name = docker_network.internal.name
  }
  volumes {
    host_path      = "/opt/nginx/sites-enabled/"
    container_path = "/etc/nginx/sites-enabled/"
  }
}