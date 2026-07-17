FROM timescale/timescaledb:latest-pg17

LABEL org.opencontainers.image.source="https://github.com/tonitert/ad-infra-k3s"

# The PostgreSQL base image selects its bitcode compiler in Makefile.global.
# Install that matching Alpine package instead of pinning an older compiler.
RUN clang_package="$(awk '/^CLANG =/ { print $3; exit }' /usr/local/lib/postgresql/pgxs/src/makefiles/../../src/Makefile.global | tr -d '-')" && \
    llvm_package="${clang_package/clang/llvm}" && \
    apk add build-base make git flex "$clang_package" "$llvm_package"

COPY system.sql /docker-entrypoint-initdb.d/100_system.sql
COPY functions.sql /docker-entrypoint-initdb.d/101_functions.sql
COPY schema.sql /docker-entrypoint-initdb.d/102_schema.sql

COPY tulip /tulip
RUN cd /tulip && make USE_PGXS=1 install && cd / && \
	git clone https://github.com/ossc-db/pg_hint_plan --branch PG17 && \
	cd pg_hint_plan && make USE_PGXS=1 install
