FROM alpine:3.22
LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

RUN apk add --no-cache iproute2 wireguard-tools wireguard-tools-wg-quick

COPY ataka/wireguard/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
