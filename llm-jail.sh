#!/usr/bin/env bash
set -euo pipefail

bash_env_dir="$(mktemp -d)"
cleanup() {
    rm -rf "$bash_env_dir"
}
trap cleanup EXIT

bash_env="$bash_env_dir/bash-env"
cat > "$bash_env" <<'EOF'
if [ -f /llmjail-env/dev-env ]; then
    . /llmjail-env/dev-env >/dev/null 2>&1 || true
fi
EOF

# llm-jail from https://github.com/braiins/llm-jail
nix run ../llm-jail/#codex -- --dangerous --vcpu 6 --mem 8192 --dev-env \
    --ro-mount "$bash_env_dir" \
    --allow-domain cache.nixos.org \
    --allow-domain channels.nixos.org \
    --allow-domain github.com --allow-domain api.github.com --allow-domain raw.githubusercontent.com \
    --allow-domain registry.npmjs.org --allow-domain pypi.org --allow-domain files.pythonhosted.org \
    --allow-domain crates.io --allow-domain static.crates.io --allow-domain cdn.crates.io \
    --allow-domain sourceforge.net --allow-domain savannah.gnu.org \
    --allow-domain bitbucket.org \
    --allow-domain tertsonen.xyz \
    --allow-domain ad.tertsonen.xyz \
    --allow-domain ctfnote.ad.tertsonen.xyz:6443 \
    --allow-domain ctfnote.ad.tertsonen.xyz:443 \
    --allow-domain ctfnote.ad.tertsonen.xyz:22 \
    --allow-domain ctfnote.ad.tertsonen.xyz:80 \
    --allow-domain 204.168.241.208 \
    -- -c shell_environment_policy.inherit=all \
    -c "shell_environment_policy.set.BASH_ENV=\"$bash_env\""
