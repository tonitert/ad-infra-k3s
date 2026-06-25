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
rendered_secret=$(mktemp)
render_error=$(mktemp)
trap 'rm -f "$rendered_secret" "$render_error"' EXIT

for template_file in secrets/chart/templates/*.yaml; do
    if [ -f "$template_file" ]; then
        # Extract filename without path and extension
        filename=$(basename "$template_file" .yaml)
        output_file="argo/secrets/${filename}-sealed.yaml"
        
        echo "Processing template: $template_file"

        if ! helm template secrets secrets/chart -s "templates/$(basename "$template_file")" > "$rendered_secret" 2> "$render_error"; then
            if grep -q "could not find template templates/$(basename "$template_file") in chart" "$render_error"; then
                rm -f "$output_file"
                echo "- Skipped empty template and removed stale output: $output_file"
                continue
            fi

            cat "$render_error" >&2
            exit 1
        fi

        if ! grep -q '[^[:space:]]' "$rendered_secret"; then
            rm -f "$output_file"
            echo "- Skipped empty template and removed stale output: $output_file"
            continue
        fi
        
        # Generate sealed secret for this template
        kubeseal --kubeconfig "$KUBECONFIG" -o yaml < "$rendered_secret" > "$output_file"

        echo "- Generated: $output_file"
    fi
done

echo "All sealed secrets generated in the argo/secrets/ directory"

echo "Installing sealed secrets..."
kubectl apply -f argo/secrets/
echo "All sealed secrets installed"
