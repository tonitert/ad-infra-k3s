#!/usr/bin/env sh

set -euo pipefail

tofu apply -var-file=./credentials.tfvars
./install-secrets.sh