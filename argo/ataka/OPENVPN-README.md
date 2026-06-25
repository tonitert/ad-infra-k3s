# Ataka OpenVPN Secret

Ataka mounts the `openvpn-config` secret into the `ctfcode` pod at `/vpn`.
Generate it through the repository-wide secrets chart:

```bash
cp secrets/chart/values.yaml.example secrets/chart/values.yaml
$EDITOR secrets/chart/values.yaml
./install-secrets.sh
```

Set `ataka.openvpnConfig` to the full contents of the OpenVPN client config.
The chart stores it as `vpn.conf`, matching `VPN_FILES=vpn.conf` in the Ataka
deployment.

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
