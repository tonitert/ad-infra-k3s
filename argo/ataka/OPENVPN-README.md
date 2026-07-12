# Ataka OpenVPN Secret

Ataka can use the `openvpn-config` secret either as the legacy `ctfcode`
sidecar config or as the Ataka VPN gateway config.
Generate it through the repository-wide secrets chart:

```bash
cp secrets/chart/values.yaml.example secrets/chart/values.yaml
$EDITOR secrets/chart/values.yaml
./install-secrets.sh
```

Set `ataka.openvpnConfig` to the full contents of the OpenVPN client config.
The secrets chart stores it as `vpn.conf`.

If the config references extra files, add them under `ataka.openvpnFiles`:

```yaml
ataka:
  openvpnConfig: |
    client
    dev tun
    ca /vpn/ca.crt
    cert /vpn/client.crt
    key /vpn/client.key
  openvpnFiles:
    ca.crt: |
      -----BEGIN CERTIFICATE-----
      ...
      -----END CERTIFICATE-----
    client.crt: |
      -----BEGIN CERTIFICATE-----
      ...
      -----END CERTIFICATE-----
    client.key: |
      -----BEGIN PRIVATE KEY-----
      ...
      -----END PRIVATE KEY-----
```

To use OpenVPN as the Ataka gateway, enable only the OpenVPN gateway in
`argo/ataka/values.yaml`:

```yaml
openvpn:
  enabled: true
  routeCidrs:
    - <ctf-network-cidr>
  gateway:
    enabled: true

wireguard:
  enabled: false
```

Only one Ataka VPN gateway can be enabled at a time. Keep WireGuard enabled for
WireGuard competitions, or disable it and enable the OpenVPN gateway for
OpenVPN competitions.
