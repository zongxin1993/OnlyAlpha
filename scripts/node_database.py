"""Explicit dev/test Node LOGIN preparation, never ordinary backend startup.

Rust startup and this operator share the read-only node_access.sql policy.
Existing unexpected identity or privileges are rejected without auto-repair.
"""
from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.database_guard import assert_test_database

CAPABILITIES = {
    "onlyalpha_job_publisher": (False, False, True),
    "onlyalpha_job_reader": (False, False, True),
    "onlyalpha_node_control": (False, True, False),
}
MARKER = "OnlyAlpha controlled Node login"
POLICY = Path(__file__).resolve().parents[1] / "packages/backend/src/persistence/node_access.sql"
ERRORS = frozenset({
    "NODE_CAPABILITY_ROLE_REFUSED", "NODE_ROLE_IDENTITY_REFUSED",
    "NODE_ROLE_MEMBERSHIP_REFUSED", "NODE_ROLE_CONFIGURATION_REFUSED",
    "NODE_ROLE_DIRECT_AUTHORITY_REFUSED", "NODE_CAPABILITY_PERMISSION_REFUSED",
})


def prepare(dsn: str, *, test: bool) -> str:
    config = conninfo_to_dict(dsn)
    if test:
        assert_test_database(dsn)
        role = "onlyalpha_node_test"
    else:
        if config.get("host") != "postgres" or config.get("dbname") != "onlyalpha":
            raise ValueError("NODE_DEV_DATABASE_REFUSED")
        role = "onlyalpha_node_runtime"
    if not config.get("password"):
        raise ValueError("NODE_PASSWORD_REQUIRED")
    policy = POLICY.read_text()
    if policy.count("$1") != 1 or "%s" in policy:
        raise ValueError("NODE_DATABASE_POLICY_UNAVAILABLE")
    # One typed parameter, with the driver's own placeholder spelling. No SQL
    # parser, interpolated role name, stored function or second policy matrix.
    policy = policy.replace("$1", "%s")
    with psycopg.connect(make_conninfo(dsn, options="-c search_path=pg_catalog,public,pg_temp")) as db:
        row = db.execute(
            "SELECT shobj_description(oid,'pg_authid') FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if row is None:
            db.execute(sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS INHERIT"
            ).format(sql.Identifier(role)))
            db.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(role), sql.Literal(MARKER)))
            db.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(config["password"])))
            for name, (_, inherit, selected) in CAPABILITIES.items():
                db.execute(sql.SQL("GRANT {} TO {} WITH ADMIN FALSE, INHERIT {}, SET {}").format(
                    sql.Identifier(name), sql.Identifier(role), sql.Literal(inherit), sql.Literal(selected)))
        elif row != (MARKER,):
            raise ValueError("NODE_ROLE_IDENTITY_REFUSED")
        result = db.execute(policy, (role,)).fetchone()
        if result != ("OK",):
            code = result[0] if result and result[0] in ERRORS else "NODE_DATABASE_POLICY_UNAVAILABLE"
            raise ValueError(code)
    return make_conninfo(dsn, user=role, sslmode="disable")


def main() -> None:
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    dsn = prepare(os.environ["ONLYALPHA_POSTGRES_DSN"], test=args.test)
    print(json.dumps({"prepared": True, "user": conninfo_to_dict(dsn)["user"]}))


if __name__ == "__main__":
    main()
