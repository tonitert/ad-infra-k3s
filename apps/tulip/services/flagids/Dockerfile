FROM python:3.10

LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

WORKDIR /app

COPY ./ /app/

COPY ./requirements.txt /app/

RUN pip install -r ./requirements.txt

COPY ./flagids.py /app/

STOPSIGNAL SIGINT

CMD ["python3", "./flagids.py"]
