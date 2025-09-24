# Gluetun OpenVPN Sidecar Setup

This deployment now includes a Gluetun sidecar container that provides OpenVPN connectivity for the main application container.

## Prerequisites

1. **OpenVPN Configuration File**: You need a valid OpenVPN configuration file (`.ovpn` or `.conf`) from your VPN provider.
2. **Sealed Secrets Controller**: This setup uses sealed secrets for secure credential management.

## Setup Instructions

### 1. Prepare OpenVPN Configuration

1. Obtain your OpenVPN configuration file from your VPN provider
2. **Important**: Replace any hostname in the `remote` directive with an IP address:
   ```bash
   # If your config has: remote vpn.example.com 1194
   # Replace with: remote 1.2.3.4 1194
   nslookup vpn.example.com  # Get the IP address
   ```
3. Ensure all referenced files (ca.crt, client.crt, client.key) use absolute paths like `/gluetun/ca.crt`

### 2. Create Sealed Secrets

Run the provided script to create sealed secrets:

```bash
cd /path/to/your/openvpn/config
./create-openvpn-sealed-secrets.sh
```

Before running, update these variables in the script:
- `OPENVPN_CONFIG_FILE`: Path to your `.ovpn` file
- `VPN_USERNAME`: Your VPN username (if required)
- `VPN_PASSWORD`: Your VPN password (if required)
- `NAMESPACE`: Kubernetes namespace (default: `default`)

### 3. Apply Sealed Secrets

```bash
kubectl apply -f openvpn-config-sealedsecret.yaml
kubectl apply -f openvpn-auth-sealedsecret.yaml
```

### 4. Deploy the Application

Deploy the updated deployment which now includes the Gluetun sidecar:

```bash
kubectl apply -f ctfcode-deployment.yaml
```

## How It Works

1. **Gluetun Sidecar**: Establishes VPN connection using your OpenVPN configuration
2. **Network Sharing**: Both containers share the same network namespace
3. **Traffic Routing**: All network traffic from the main container is routed through the VPN
4. **Security**: The sidecar runs with `NET_ADMIN` capability to manage network interfaces

## Configuration Options

The Gluetun container supports various environment variables:

- `VPN_SERVICE_PROVIDER=custom`: Uses custom OpenVPN config
- `OPENVPN_CUSTOM_CONFIG=/gluetun/custom.conf`: Path to config file
- `FIREWALL_OUTBOUND_SUBNETS`: Allows local network access (configured for common private ranges)

## Troubleshooting

### Check Gluetun Status
```bash
kubectl logs deployment/ctfcode -c gluetun
```

### Check Main Container
```bash
kubectl logs deployment/ctfcode -c ctfcode
```

### Test VPN Connection
```bash
kubectl exec deployment/ctfcode -c ctfcode -- curl -s https://ipinfo.io/ip
```

### Common Issues

1. **DNS Resolution**: Ensure hostnames in OpenVPN config are replaced with IP addresses
2. **File Paths**: Referenced files in OpenVPN config must use absolute paths starting with `/gluetun/`
3. **Permissions**: The main container may need specific network permissions depending on the application

## Security Considerations

- The TUN device is mounted from the host (`/dev/net/tun`)
- Gluetun runs with `NET_ADMIN` capability
- Secrets are encrypted using Sealed Secrets
- Local network access is allowed for cluster communication

## Additional Files Support

If your OpenVPN config references additional files (CA certificates, client certificates, etc.), add them to the secret:

```bash
kubectl create secret generic openvpn-config \
    --from-file=custom.conf=your-config.ovpn \
    --from-file=ca.crt=your-ca.crt \
    --from-file=client.crt=your-client.crt \
    --from-file=client.key=your-client.key \
    --dry-run=client -o yaml | \
kubeseal --format yaml > openvpn-config-sealedsecret.yaml
```

Make sure to update the paths in your OpenVPN config to use `/gluetun/filename`.