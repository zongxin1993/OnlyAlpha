from __future__ import annotations

from testcontainers.core.container import DockerContainer

IMAGE = "alpine:3.22.1"
EXPECTED = b"onlyalpha-testcontainers"


def main() -> int:
    with DockerContainer(IMAGE).with_command("sleep 30") as container:
        result = container.get_wrapped_container().exec_run(["sh", "-c", "printf onlyalpha-testcontainers"])
        if result.exit_code != 0:
            raise RuntimeError(f"testcontainers exec failed with exit code {result.exit_code}")
        if result.output != EXPECTED:
            raise RuntimeError(f"unexpected testcontainers output: {result.output!r}")
    print("Testcontainers disposable-container smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
