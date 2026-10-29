-- Restricted runtime role for QueryMind-AI.
-- Run after db/schema.sql, using the administrative connection.
--
-- Replace CHANGE_ME_WITH_A_LONG_RANDOM_PASSWORD before running, or create the
-- role without a password and set it separately in the Supabase dashboard.
-- Never use this role for schema changes or CSV ingestion.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_runtime') THEN
        CREATE ROLE sales_runtime
            LOGIN
            PASSWORD 'CHANGE_ME_WITH_A_LONG_RANDOM_PASSWORD'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
    END IF;
END
$$;

ALTER ROLE sales_runtime SET statement_timeout = '10s';
ALTER ROLE sales_runtime SET idle_in_transaction_session_timeout = '15s';
ALTER ROLE sales_runtime SET lock_timeout = '5s';
ALTER ROLE sales_runtime CONNECTION LIMIT 5;
ALTER ROLE sales_runtime SET default_transaction_read_only = on;
ALTER ROLE sales_runtime SET search_path = public;

DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO sales_runtime',
        current_database()
    );
END
$$;

REVOKE ALL ON SCHEMA public FROM sales_runtime;
GRANT USAGE ON SCHEMA public TO sales_runtime;

REVOKE ALL PRIVILEGES ON TABLE public.sales_transactions FROM sales_runtime;
REVOKE ALL PRIVILEGES ON TABLE public.v_sales FROM sales_runtime;
GRANT SELECT ON TABLE public.sales_transactions TO sales_runtime;
GRANT SELECT ON TABLE public.v_sales TO sales_runtime;
