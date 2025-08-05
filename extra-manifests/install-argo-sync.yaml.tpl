apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: argo-config
  namespace: argocd
spec:
  project: default
  source:
    path: argo/argo
    repoURL: '${repo_url}'
    targetRevision: HEAD
    helm:
      values: |
        repoUrl: '${repo_url}'
  destination:
    namespace: argocd
    server: "https://kubernetes.default.svc"
