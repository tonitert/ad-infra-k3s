apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - https://github.com/argoproj/argo-cd/manifests/crds?ref=v3.0.12
  - https://github.com/kubernetes-sigs/gateway-api/config/crd/experimental?ref=v1.3.0
  - namespace.yaml 
