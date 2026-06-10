apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: argo-config
  namespace: argocd
spec:
  project: default
  syncPolicy:
    automated: {}
  source:
    path: argo/argo
    repoURL: '${repo_url}'
    targetRevision: '${repo_revision}'
    helm:
      values: |
        repoUrl: '${repo_url}'
        repoRevision: '${repo_revision}'
  destination:
    namespace: argocd
    server: "https://kubernetes.default.svc"
