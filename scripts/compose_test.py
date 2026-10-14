"""Run environment-dependent tests against isolated databases in dev Compose."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import psycopg

from onlyalpha.persistence.postgres import only_assert_postgres_test_database


def main() -> int:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    database = dsn.rsplit("/", 1)[-1]
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        if exists is None:
            connection.execute(f'CREATE DATABASE "{database}"')
    if len(sys.argv) < 2:
        raise ValueError("COMPOSE_TEST_COMMAND_REQUIRED")
    command = sys.argv[1:]
    if "research-postgres" in command:
        provenance_command = [sys.executable, "scripts/embed_build_provenance.py"]
        if os.environ.get("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID"):
            provenance_command.append("--check")
        subprocess.run(provenance_command, check=True)
    lock_fd = os.environ.get("ONLYALPHA_DEV_VERIFICATION_LOCK_FD")
    inherited = (int(lock_fd),) if lock_fd is not None else ()
    for descriptor in inherited:
        os.fstat(descriptor)
    completed = subprocess.run(command, check=False, pass_fds=inherited)
    if inherited and completed.returncode < 0:
        # sys.exit(-signal) would encode this as an ordinary positive exit and
        # incorrectly settle the dev launcher's UNKNOWN lifecycle fence.
        number = -completed.returncode
        if number != signal.SIGKILL:
            signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
