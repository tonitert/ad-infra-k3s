terraform {
  backend "http" {}
}

# Fix problem with GitHub Actions
provider "github" {
    token = var.github_token
}

variable "github_token" {
    sensitive = true
    default = null
}
