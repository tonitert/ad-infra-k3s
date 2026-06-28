# General

The project sets up a Kubernetes cluster on Hetzner with services needed for playing Attack/Defense CTF competitions.
You are running in a sandbox with internet access to specified domains only. If more access is strictly required to perform the task, ask the user to whitelist the domain. The sandbox is defined in ./llm-jail.sh
The configuration must be production ready and applyable from scratch from the files in this repository. There should be no manual steps required to deploy the cluster, running terraform apply must be enough.
You have access to a development kubernetes cluster. The kubeconfig is in k3s_kubeconfig.yaml. The cluster might time out sometimes, retry a couple of times when this happens.
Do not use configmaps for source code. If a configmap has a code file that is explictly configuration, that is fine. Ataka and tulip can be modified and their containers pushed to the github repo. Prompt the user to do this when you modify the service sources.
HTTP traffic to services is proxied through traefik.

# Services

## Tulip

Tulip is a network traffic inspector. One pod ingests PCAPs from the vulnbox machine, which are pulled in with rsync from a remote host. Tulip exposes a web interface to inspect traffic for exploits against A/D services in a dedicated vulnbox machine.

## Ataka

Ataka is a exploit automation tool. It automatically executes exploits against other teams during the CTF. Ataka has a player cli, that you can download from ataka.ad.tertsonen.xyz with the ataka basic auth credentials.

# Secrets

install-secrets.sh installs the secrets for services from the chart at secrets/. The secrets such as basic auth passwords are available at secrets/values.yaml

# Scripts

ArgoCD can be accessed by running connect-argocd-locally.sh. This script port forwards argocd to the current machine and gives the credentials to access it.
use install-secrets.sh for creating secrets.