{
  description = "Development shell for ad-infra-k3s";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };

          infraTools = with pkgs; [
            terraform
            opentofu
            packer
            hcloud
            kubectl
            kubernetes-helm
            kustomize
            kubeseal
            argocd
          ];

          supportTools = with pkgs; [
            bashInteractive
            coreutils
            curl
            docker-client
            docker-compose
            git
            jq
            openssh
            pre-commit
            terraform-docs
            terraform-ls
            tfsec
            tflint
            yq-go
            ripgrep
            zsh
          ];
        in
        {
          default = pkgs.mkShell {
            packages = infraTools ++ supportTools;

            shellHook = ''
              if [ -f "$PWD/clustername_kubeconfig.yaml" ] && [ -z "''${KUBECONFIG:-}" ]; then
                export KUBECONFIG="$PWD/clustername_kubeconfig.yaml"
              fi

              source .env

              echo "ad-infra-k3s devshell: terraform, packer, hcloud, kubectl, helm, kubeseal"

              if [ -z "''${AD_INFRA_K3S_ZSH:-}" ] && [ -t 0 ] && [ -t 1 ]; then
                export AD_INFRA_K3S_ZSH=1
                exec zsh
              fi
            '';
          };
        });
    };
}
