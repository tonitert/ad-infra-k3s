terraform {
    backend "http" {
      
    }

    required_version = ">= 1.5.0"
    required_providers {
      hcloud = {
        source  = "hetznercloud/hcloud"
        version = ">= 1.51.0"
      }
      github = {
          source = "integrations/github"
          version = "5.44.0"
      }

    }
}

# Fix problem with GitHub Actions
provider "github" {
}

variable "github_token" {
    sensitive = true
    default = null
}
