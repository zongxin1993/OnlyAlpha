"""Explicit dev/test preparation of a least-privilege factor-builder login.

Never called by ordinary backend startup or a validation round implicitly.
Passwords are supplied by the owning environment and are never logged.
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts.database_guard import assert_test_database


def prepare(dsn: str, *, test: bool) -> str:
    config = conninfo_to_dict(dsn)
    if test:
        assert_test_database(dsn)
        role = "onlyalpha_factor_builder_test"
    else:
        if config.get("host") != "postgres" or config.get("dbname") != "onlyalpha":
            raise ValueError("FACTOR_BUILD_DEV_DATABASE_REFUSED")
        role = "onlyalpha_factor_builder_runtime"
    if not config.get("password"):
        raise ValueError("FACTOR_BUILD_PASSWORD_REQUIRED")
    marker = "OnlyAlpha controlled factor build login"
    with psycopg.connect(dsn) as db:
        row = db.execute(
            "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,shobj_description(oid,'pg_authid') FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        ).fetchone()
        if row:
            if row != (True, False, False, False, False, False, False, marker):
                raise ValueError("FACTOR_BUILD_ROLE_IDENTITY_REFUSED")
            parents = db.execute(
                "SELECT parent.rolname FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles child ON child.oid=m.member JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid WHERE child.rolname=%s",
                (role,),
            ).fetchall()
            if parents != [("onlyalpha_factor_builder",)]:
                raise ValueError("FACTOR_BUILD_ROLE_MEMBERSHIP_REFUSED")
        else:
            db.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(sql.Identifier(role))
            )
            db.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(role), sql.Literal(marker)))
            db.execute(sql.SQL("GRANT onlyalpha_factor_builder TO {}").format(sql.Identifier(role)))
            db.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(config["password"]))
            )
    return make_conninfo(dsn, user=role, sslmode="disable")


def main() -> None:
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    dsn = prepare(os.environ["ONLYALPHA_POSTGRES_DSN"], test=args.test)
    # No credential or whole DSN is printed.
    print(json.dumps({"prepared": True, "user": conninfo_to_dict(dsn)["user"]}))


if __name__ == "__main__":
    main()
