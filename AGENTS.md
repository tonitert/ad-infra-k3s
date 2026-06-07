# General

The project sets up a Kubernetes cluster on Hetzner with services needed for playing Attack/Defense CTF competitions.
Activate a Nix devshell with nix develop to get needed tools.
The devshell is defined in flake.nix.
You are running in a sandbox with internet access to specified domains only. If more access is strictly required to perform the task, ask the user to whitelist the domain.
