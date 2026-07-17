#!/usr/bin/env bash
set -euo pipefail

image_prefix="${TULIP_IMAGE_PREFIX:-ghcr.io/tonitert/ad-infra-k3s}"
tag="${TULIP_IMAGE_TAG:-latest}"

images=(
  "tulip-frontend:apps/tulip/frontend/Dockerfile-frontend:apps/tulip/frontend"
  "tulip-api:apps/tulip/services/api/Dockerfile-api:apps/tulip/services/api"
  "tulip-flagids:apps/tulip/services/flagids/Dockerfile:apps/tulip/services/flagids"
  "tulip-assembler:apps/tulip/services/go-importer/Dockerfile-assembler:apps/tulip/services/go-importer"
  "tulip-enricher:apps/tulip/services/go-importer/Dockerfile-enricher:apps/tulip/services/go-importer"
  "tulip-timescale:apps/tulip/services/timescale/Dockerfile:apps/tulip/services/timescale"
)

for image in "${images[@]}"; do
  name="${image%%:*}"
  remainder="${image#*:}"
  dockerfile="${remainder%%:*}"
  context="${remainder#*:}"
  full_image="${image_prefix}/${name}:${tag}"

  echo "Building and pushing ${full_image} from ${dockerfile}"
  docker build --network=host --push -t "$full_image" -f "$dockerfile" "$context"
done
