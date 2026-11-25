\set ON_ERROR_STOP on
\pset pager off

-- Read-only discovery. This file contains SELECT statements only.
SELECT current_user AS connected_role, current_database() AS connected_database;

SELECT
    datname AS database_name,
    pg_get_userbyid(datdba) AS owner,
    datallowconn AS allows_connections
FROM pg_database
ORDER BY datname;

SELECT
    rolname AS role_name,
    rolsuper AS is_superuser,
    rolcreatedb AS can_create_database,
    rolcreaterole AS can_create_role,
    rolcanlogin AS can_login
FROM pg_roles
ORDER BY rolname;

SELECT
    datname AS target_database,
    pg_get_userbyid(datdba) AS owner
FROM pg_database
WHERE datname = 'privacyguard_platform';

SELECT
    rolname AS target_role,
    rolcanlogin AS can_login
FROM pg_roles
WHERE rolname IN (
    'privacyguard_platform_owner',
    'privacyguard_platform_migrator',
    'privacyguard_platform_runtime'
)
ORDER BY rolname;
