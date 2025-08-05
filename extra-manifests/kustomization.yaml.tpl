apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - https://github.com/argoproj/argo-cd/manifests/crds?ref=v3.0.12
  - namespace.yaml
  - helm-chart.yaml
  - install-argo-sync.yaml