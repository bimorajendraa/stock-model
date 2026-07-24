# timescale/timescaledb-ha (the "-all" bundle) turned out to be a
# Patroni/HA-cluster image that ignores POSTGRES_USER/PASSWORD the way a
# plain docker-compose setup expects (its own credential bootstrap model
# instead) -- wrong fit for local/single-node dev. This builds pgvector on
# top of the standard, docker-compose-friendly TimescaleDB image instead.
# That base image is Alpine (not Debian), hence apk, not apt-get.
FROM timescale/timescaledb:latest-pg16

RUN apk add --no-cache postgresql-pgvector
