#!/bin/bash

# Script to create sealed secrets for OpenVPN configuration
# Usage: 
# 1. First, create your OpenVPN config file (e.g., custom.conf)
# 2. Update the variables below with your actual values
# 3. Run this script to generate sealed secrets

# Configuration variables - UPDATE THESE
OPENVPN_CONFIG_FILE="custom.conf"  # Path to your OpenVPN config file
VPN_USERNAME="your-vpn-username"
VPN_PASSWORD="your-vpn-password"
NAMESPACE="default"  # Update if using different namespace

echo "Creating OpenVPN configuration sealed secret..."

# Check if OpenVPN config file exists
if [ ! -f "$OPENVPN_CONFIG_FILE" ]; then
    echo "Error: OpenVPN config file '$OPENVPN_CONFIG_FILE' not found!"
    echo "Please create your OpenVPN configuration file first."
    exit 1
fi

# Create temporary secret for OpenVPN config
kubectl create secret generic openvpn-config \
    --from-file=custom.conf="$OPENVPN_CONFIG_FILE" \
    --namespace="$NAMESPACE" \
    --dry-run=client -o yaml | \
kubeseal --format yaml > openvpn-config-sealedsecret.yaml

# Create temporary secret for OpenVPN auth
kubectl create secret generic openvpn-auth \
    --from-literal=username="$VPN_USERNAME" \
    --from-literal=password="$VPN_PASSWORD" \
    --namespace="$NAMESPACE" \
    --dry-run=client -o yaml | \
kubeseal --format yaml > openvpn-auth-sealedsecret.yaml

echo "Sealed secrets created:"
echo "- openvpn-config-sealedsecret.yaml"
echo "- openvpn-auth-sealedsecret.yaml"
echo ""
echo "Please review the generated files and apply them to your cluster:"
echo "kubectl apply -f openvpn-config-sealedsecret.yaml"
echo "kubectl apply -f openvpn-auth-sealedsecret.yaml"