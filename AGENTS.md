# General

The project sets up a Kubernetes cluster on Hetzner with services needed for playing Attack/Defense CTF competitions.
Activate a Nix devshell with nix develop to get needed tools.
The devshell is defined in flake.nix.
You are running in a sandbox with internet access to specified domains only. If more access is strictly required to perform the task, ask the user to whitelist the domain. The sandbox is defined in ./llm-jail.sh
The configuration must be production ready and applyable from scratch from the files in this repository. There should be no manual steps required to deploy the cluster, running terraform apply must be enough.
You have access to a development kubernetes cluster. The kubeconfig is in clustername_kubeconfig.yaml

## Scripts

ArgoCD can be accessed by running connect-argocd-locally.sh. This script port forwards argocd to the current machine and gives the credentials to access it.
use install-secrets.sh for creating secrets.