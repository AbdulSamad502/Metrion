-- auth.md §7.3: two database roles, cluster-level, created once at bootstrap — not by any
-- package's migration history, since a role isn't owned by a single schema/package and role
-- creation isn't naturally idempotent-per-migration the way table DDL is.
--
--   metrion_migrate — table owner, runs DDL (Alembic). Never used to serve requests.
--   metrion_app     — runtime application and workers. Non-owner, non-superuser, NO BYPASSRLS.
--                     This is the role RLS is actually enforced against.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metrion_migrate') THEN
    CREATE ROLE metrion_migrate LOGIN PASSWORD 'metrion_migrate_dev_password';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metrion_app') THEN
    CREATE ROLE metrion_app LOGIN PASSWORD 'metrion_app_dev_password' NOBYPASSRLS;
  END IF;
END
$$;

GRANT ALL ON SCHEMA public TO metrion_migrate;
GRANT USAGE ON SCHEMA public TO metrion_app;

ALTER DEFAULT PRIVILEGES FOR ROLE metrion_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO metrion_app;
