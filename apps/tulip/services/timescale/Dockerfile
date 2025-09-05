FROM timescale/timescaledb:latest-pg15

LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

RUN apk add build-base make clang15 llvm15 git

COPY system.sql /docker-entrypoint-initdb.d/100_system.sql
COPY functions.sql /docker-entrypoint-initdb.d/101_functions.sql
COPY schema.sql /docker-entrypoint-initdb.d/102_schema.sql

COPY tulip /tulip
RUN cd /tulip && make USE_PGXS=1 install && cd / && \
	git clone https://github.com/ossc-db/pg_hint_plan --branch PG15 && \
	cd pg_hint_plan && make USE_PGXS=1 install
