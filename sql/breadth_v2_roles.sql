-- Run as the database owner after migrations. These NOLOGIN group roles keep
-- migration, write, and render/read responsibilities distinct.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'breadth_v2_reader') THEN
        CREATE ROLE breadth_v2_reader NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'breadth_v2_writer') THEN
        CREATE ROLE breadth_v2_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'breadth_v2_migrator') THEN
        CREATE ROLE breadth_v2_migrator NOLOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA breadth_v2 FROM PUBLIC;
GRANT USAGE ON SCHEMA breadth_v2 TO breadth_v2_reader, breadth_v2_writer;
GRANT USAGE, CREATE ON SCHEMA breadth_v2 TO breadth_v2_migrator;

GRANT SELECT ON ALL TABLES IN SCHEMA breadth_v2 TO breadth_v2_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA breadth_v2 TO breadth_v2_writer;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA breadth_v2 TO breadth_v2_migrator;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA breadth_v2 TO breadth_v2_writer;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA breadth_v2 TO breadth_v2_migrator;

ALTER DEFAULT PRIVILEGES IN SCHEMA breadth_v2
    GRANT SELECT ON TABLES TO breadth_v2_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA breadth_v2
    GRANT SELECT, INSERT, UPDATE ON TABLES TO breadth_v2_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA breadth_v2
    GRANT USAGE, SELECT ON SEQUENCES TO breadth_v2_writer;
