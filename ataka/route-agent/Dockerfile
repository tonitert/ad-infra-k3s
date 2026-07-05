FROM ghcr.io/tonitert/ad-infra-k3s/ataka-executor:latest
LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

COPY ataka/route-agent/route_agent.py /route_agent.py

ENTRYPOINT ["python", "/route_agent.py"]
