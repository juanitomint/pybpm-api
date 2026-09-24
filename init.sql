-- Enable UUID generation extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- PostgreSQL 18+ standard UUID support
-- uuidv7() is available without extension in PG 18+
