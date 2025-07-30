FROM alpine:latest

RUN apk add --no-cache \
    task kubectl age flux=2.4.0 sops jq kustomize kubeconform yq terraform ansible=11.8.0-r0

RUN cd k3s && workstation:venv