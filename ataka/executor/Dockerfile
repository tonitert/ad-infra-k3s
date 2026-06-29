FROM docker:28.4.0
LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

RUN apk add --no-cache python3 python3-dev py3-pip git build-base

RUN pip install --break-system-packages --no-cache-dir --upgrade pip

WORKDIR /

COPY ataka/common/requirements.txt /ataka/common/
RUN pip install --break-system-packages --no-cache-dir -r /ataka/common/requirements.txt
COPY ataka/common /ataka/common

VOLUME /data/shared
VOLUME /data/exploits
VOLUME /data/persist

COPY ataka/executor/requirements.txt /ataka/executor/
RUN pip install --break-system-packages --no-cache-dir -r /ataka/executor/requirements.txt
COPY ataka/executor /ataka/executor

CMD [ "sh", "/ataka/common/delayed_start.sh", "--", "python", "-m", "ataka.executor" ]
