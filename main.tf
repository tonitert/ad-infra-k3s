terraform {
  backend "http" {}
}

# Fix problem with GitHub Actions
provider "github" {}