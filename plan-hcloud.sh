#!/usr/bin/env bash

# This script is used to run the Terraform plan for the AD infrastructure project.

terraform plan \
  -var-file="credentials.tfvars" \
  -out="plan.out"