# Kubernetes A/D Infrastructure

This repository provides a fully IaC solution for deploying infrastructure for A/D CTFs. All configuration is done inside the Git repository. 

## Credentials

Run commands from a Nix devshell so Terraform, Packer, `kubectl`, Helm, and `kubeseal` are available:

```bash
nix develop
```

### Local deployment credentials

Create `credentials.tfvars` for local Terraform runs. This file is ignored by Git.

```bash
cp credentials.tfvars.example credentials.tfvars
```

The Hetzner token needs read/write access to the Hetzner Cloud project. The Cloudflare token needs permission to edit DNS records for the `tertsonen.xyz` zone because Terraform manages `ctfnote.ad.tertsonen.xyz` and `tulip.ad.tertsonen.xyz`.

If you use the shared GitLab HTTP Terraform state backend, initialize Terraform with backend credentials using a GitLab state token:

```hcl
address        = "https://gitlab.com/api/v4/projects/72135661/terraform/state/cluster"
lock_address   = "https://gitlab.com/api/v4/projects/72135661/terraform/state/cluster/lock"
unlock_address = "https://gitlab.com/api/v4/projects/72135661/terraform/state/cluster/lock"
username       = "token"
password       = "<gitlab-state-token>"
lock_method    = "POST"
unlock_method  = "DELETE"
retry_wait_min = "5"
```

Terraform also needs an SSH key pair for provisioning nodes. By default it reads:

```text
keys/ssh
keys/ssh.pub
```

Alternatively, pass `ssh_key_path` in `credentials.tfvars` to point at another private key path. The matching public key is expected at the same path with `.pub` appended.

For local Packer image builds, export the Hetzner token as `HCLOUD_TOKEN`:

```bash
export HCLOUD_TOKEN="<hetzner-cloud-read-write-token>"
```

### GitHub Actions secrets

The Terraform workflow expects these repository secrets:

| Secret | Used for |
| --- | --- |
| `HCLOUD_TOKEN` | Hetzner Cloud Terraform provider and Packer builds. |
| `CLOUDFLARE_TOKEN` | Cloudflare DNS records. |
| `SSH_PRIVATE_KEY` | Private SSH key written to `keys/ssh` during the workflow. |
| `SSH_PUBLIC_KEY` | Public SSH key written to `keys/ssh.pub` during the workflow. |
| `GITLAB_STATE_TOKEN` | GitLab HTTP Terraform state backend password. |
| `TF_VIA_PR_PASS` | Encrypting Terraform plans posted by `tf-via-pr`. |

`GITHUB_TOKEN` is the built-in GitHub Actions token; it does not need to be added manually.

### Application secrets

CTFNote and HedgeDoc secrets are rendered from `secrets/chart` and sealed into `argo/secrets` by `install-secrets.sh`.

Before running `install-secrets.sh`, create the ignored file `secrets/chart/values.yaml`:

```yaml
basicAuthUsername: "<username>"
basicAuthPassword: "<password>"
```

Then generate sealed secrets:

```bash
./install-secrets.sh
```

The generated sealed secrets include:

| Kubernetes secret | Namespace | Purpose |
| --- | --- | --- |
| `ctfnote-secrets` | `ctfnote` | Generated PostgreSQL admin password for CTFNote and HedgeDoc. |
| `ctfnote-pad-basic-auth` | `ctfnote` | Basic-auth htpasswd entry for HedgeDoc and Tulip routes. |

Keep the original `basicAuthPassword` somewhere safe. The cluster stores only the htpasswd hash in `ctfnote-pad-basic-auth`, not the plaintext password.

### Deployed cluster credentials

Write a kubeconfig from Terraform output:

```bash
terraform output --raw kubeconfig > clustername_kubeconfig.yaml
export KUBECONFIG="$PWD/clustername_kubeconfig.yaml"
```

Get the initial ArgoCD admin password:

```bash
./get-argocd-password.sh
```

Or manually:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

## ArgoCD

ArgoCD is used for deploying the various services from the Git repo. The UI can be accessed via port-forwarding.

## Services

### CTFNote

HedgeDoc uses the `basicAuthUsername` and `basicAuthPassword` from `secrets/chart/values.yaml` at the time the sealed secrets were generated.

```bash
kubectl -n ctfnote get secret ctfnote-pad-basic-auth -o jsonpath='{.data.auth}' | base64 -d
```

This prints the htpasswd entry, which is useful for checking the configured username and hash but does not reveal the plaintext password.
