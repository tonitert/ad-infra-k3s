terraform {
  backend "http" {}
  required_providers {
    github = {
        source = "integrations/github"
        version = "6.6.0"
    }
  }
}

# Fix problem with GitHub Actions
provider "github" {
    token = var.github_token
}

variable "github_token" {
    sensitive = true
    default = null
}
