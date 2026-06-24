#!/usr/bin/env bash

set -e

echo "Loading kubeconfig..."

if [ -n "${KUBECONFIG:-}" ]; then
    export KUBECONFIG
elif [ -s k3s_kubeconfig.yaml ]; then
    export KUBECONFIG=$(pwd)/k3s_kubeconfig.yaml
else
    terraform output --raw kubeconfig > k3s_kubeconfig.yaml
    export KUBECONFIG=$(pwd)/k3s_kubeconfig.yaml
fi

# Generate sealed secrets from helm templates
echo "Generating sealed secrets..."

# Create output directory for sealed secrets in argo directory
mkdir -p argo/secrets

# Process each template file dynamically
for template_file in secrets/chart/templates/*.yaml; do
    if [ -f "$template_file" ]; then
        # Extract filename without path and extension
        filename=$(basename "$template_file" .yaml)
        
        echo "Processing template: $template_file"
        
        # Generate sealed secret for this template
        helm template secrets secrets/chart -s "templates/$(basename "$template_file")" | kubeseal --kubeconfig "$KUBECONFIG" -o yaml > "argo/secrets/${filename}-sealed.yaml"

        echo "- Generated: argo/secrets/${filename}-sealed.yaml"
    fi
done

echo "All sealed secrets generated in the argo/secrets/ directory"

echo "Installing sealed secrets..."
kubectl apply -f argo/secrets/
echo "All sealed secrets installed"
