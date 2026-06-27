FROM python:3.11-slim
LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

RUN pip install --no-cache-dir --upgrade pip

WORKDIR /

COPY ataka/common/requirements.txt /ataka/common/
RUN pip install --no-cache-dir -r /ataka/common/requirements.txt
COPY ataka/common /ataka/common

VOLUME /ataka/ctfconfig
VOLUME /data/shared

COPY ataka/player-cli /ataka/player-cli
RUN chmod +x /ataka/player-cli/package_player_cli.sh \
    && test -x /ataka/player-cli/package_player_cli.sh

COPY ataka/ctfcode/requirements.txt /ataka/ctfcode/
RUN pip install --no-cache-dir -r /ataka/ctfcode/requirements.txt
COPY ataka/ctfcode /ataka/ctfcode

CMD [ "bash", "/ataka/common/delayed_start.sh", "--", "python", "-m", "ataka.ctfcode" ]
