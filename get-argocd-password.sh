#!/usr/bin/env bash

export KUBECONFIG=$(pwd)/clustername_kubeconfig.yaml

kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d