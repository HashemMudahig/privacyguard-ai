\set ON_ERROR_STOP on

-- This script is only for a confirmed fresh installation. Run the read-only
-- discover_platform_postgres.sql first. It aborts if any target object exists.
SELECT NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'privacyguard_platform'
) AND NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname IN (
        'privacyguard_platform_owner',
        'privacyguard_platform_migrator',
        'privacyguard_platform_runtime'
    )
) AS target_is_clear \gset

\if :target_is_clear
\else
    \echo 'ABORT: target database or role already exists; inspect and reconcile manually.'
    \quit 3
\endif

\prompt 'Type APPROVE NEW PRIVACYGUARD PLATFORM to continue: ' approval_text
SELECT :'approval_text' = 'APPROVE NEW PRIVACYGUARD PLATFORM' AS approved \gset
\if :approved
\else
    \echo 'ABORT: explicit approval phrase was not provided.'
    \quit 3
\endif

-- Passwords are prompted without echo and never stored in this file.
\prompt -s 'Migration role password: ' migration_password
\prompt -s 'Runtime role password: ' runtime_password

CREATE ROLE privacyguard_platform_owner
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE privacyguard_platform_migrator
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD :'migration_password';
CREATE ROLE privacyguard_platform_runtime
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD :'runtime_password';

GRANT privacyguard_platform_owner TO privacyguard_platform_migrator;
CREATE DATABASE privacyguard_platform OWNER privacyguard_platform_owner;

REVOKE CONNECT ON DATABASE privacyguard_platform FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE privacyguard_platform FROM PUBLIC;
GRANT CONNECT ON DATABASE privacyguard_platform
    TO privacyguard_platform_migrator, privacyguard_platform_runtime;
ALTER ROLE privacyguard_platform_migrator IN DATABASE privacyguard_platform
    SET ROLE privacyguard_platform_owner;

\connect privacyguard_platform

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO privacyguard_platform_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE privacyguard_platform_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO privacyguard_platform_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE privacyguard_platform_owner IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO privacyguard_platform_runtime;

\unset approval_text
\unset migration_password
\unset runtime_password
