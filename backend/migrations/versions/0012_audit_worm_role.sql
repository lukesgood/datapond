-- The role that makes the audit tables append-only in fact rather than by convention.
--
-- 0005 made security_audit_log and auth_audit_log append-only and said plainly what it
-- could not do: the application connects as the role that OWNS those tables, and an
-- owner can re-grant itself any privilege, disable the trigger, or drop it outright.
-- What 0005 asked for is a role that does NOT own them, holding only SELECT and INSERT.
-- This creates that role. tool_call_log (0008) carries the same trigger and joins it.
--
-- NOT A CUTOVER. Creating the role changes nothing on its own: the application keeps
-- connecting as whatever POSTGRES_USER says until an operator points it here and sets a
-- password. docs/DEPLOY_SINGLE_NODE.md carries that procedure, and it is deliberately
-- manual — a wrong grant here locks the product out of its own database.
--
-- NOLOGIN on purpose: a role that cannot authenticate cannot be used by accident, and
-- the operator's ALTER ROLE ... LOGIN PASSWORD is the moment the cutover becomes real.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datapond_app') THEN
        CREATE ROLE datapond_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO datapond_app;

-- Everything the product reads and writes in the ordinary course.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO datapond_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO datapond_app;

-- …except the audit tables, which this role may only append to and read. REVOKE after
-- the blanket GRANT above, in this order, because the blanket grant would otherwise
-- hand back what is taken here.
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
    public.security_audit_log, public.auth_audit_log, public.tool_call_log
    FROM datapond_app;

-- Tables created by later migrations must land the same way, or a table added next
-- month silently arrives with no grants and the application 500s on it.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO datapond_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO datapond_app;
