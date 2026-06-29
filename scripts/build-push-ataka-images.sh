#!/usr/bin/env bash
set -euo pipefail

image_prefix="${ATAKA_IMAGE_PREFIX:-ghcr.io/tonitert/ad-infra-k3s}"
tag="${ATAKA_IMAGE_TAG:-latest}"

images=(
  "ataka-api:ataka/api/Dockerfile"
  "ataka-cli:ataka/cli/Dockerfile"
  "ataka-ctfcode:ataka/ctfcode/Dockerfile"
  "ataka-executor:ataka/executor/Dockerfile"
  "ataka-wireguard:ataka/wireguard/Dockerfile"
)

for image in "${images[@]}"; do
  name="${image%%:*}"
  dockerfile="${image#*:}"
  full_image="${image_prefix}/${name}:${tag}"

  echo "Building and pushing ${full_image} from ${dockerfile}"
  docker build --push -t "$full_image" -f "$dockerfile" .
done
