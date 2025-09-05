# Kubernetes A/D Infrastructure

This repository provides a fully IaC solution for deploying infrastructure for A/D CTFs. All configuration is done inside the Git repository. 

## ArgoCD

ArgoCD is used for deploying the various services from the Git repo. The UI can be accessed via port-forwarding.

## Services

### CTFNote

The basic auth password for hedgedoc can be obtained with: 

```bash
kubectl -n ctfnote get secret ctfnote-pad-basic-auth -o jsonpath='{.data.password}' | base64 -d
```