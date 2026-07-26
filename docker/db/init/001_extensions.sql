-- Enable extensions the schema depends on. Runs once, on first container
-- init. Mounted as a bind mount at /docker-entrypoint-initdb.d in
-- docker-compose.yml, which replaces that directory entirely -- the base
-- timescale/timescaledb image's own bundled init scripts never run here,
-- only this file does (verified directly: `docker exec <container> ls
-- /docker-entrypoint-initdb.d` shows only this file). That's why both
-- extensions are created explicitly here rather than relying on the base
-- image's own timescaledb bootstrap.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
