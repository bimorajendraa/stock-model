-- Enable extensions the schema depends on. Runs once, on first container init.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
