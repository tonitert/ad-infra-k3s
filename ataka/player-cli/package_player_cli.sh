#!/bin/bash

set -e
set -u

TMPFILE="$(mktemp -d)"
trap "rm -rf '$TMPFILE'" 0               # EXIT
trap "rm -rf '$TMPFILE'; exit 1" 2       # INT
trap "rm -rf '$TMPFILE'; exit 1" 1 15    # HUP TERM

cd "$TMPFILE"
cp -r /ataka/player-cli .
chmod -R u+w player-cli
cp "/ataka/ctfconfig/$CTF.py" player-cli/player_cli/ctfconfig.py
mkdir -p player-cli/ataka/common
cp /ataka/common/flag_status.py player-cli/ataka/common/flag_status.py
python - <<'PY'
import os
from pathlib import Path

Path("player-cli/player_cli/auth.py").write_text(
    "BASIC_AUTH_USERNAME = {!r}\n"
    "BASIC_AUTH_PASSWORD = {!r}\n"
    "DEFAULT_ATAKA_BASE_URL = {!r}\n\n"
    "def get_basic_auth():\n"
    "    if BASIC_AUTH_USERNAME and BASIC_AUTH_PASSWORD:\n"
    "        return BASIC_AUTH_USERNAME, BASIC_AUTH_PASSWORD\n"
    "    return None\n".format(
        os.environ["ATAKA_BASIC_AUTH_USERNAME"],
        os.environ["ATAKA_BASIC_AUTH_PASSWORD"],
        os.environ["ATAKA_PUBLIC_URL"],
    )
)
PY
pip install -r player-cli/requirements.txt --target player-cli/
python -m zipapp -c --python "/usr/bin/env python3" --output "$TMPFILE/ataka-player-cli.pyz" player-cli/
python "$TMPFILE/ataka-player-cli.pyz" --help >/dev/null
mv "$TMPFILE/ataka-player-cli.pyz" /data/shared/ataka-player-cli.pyz
echo 'Python player created'
