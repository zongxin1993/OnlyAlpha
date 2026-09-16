"""Test-only Product API process with the RuntimeGeneration contract fake."""

from onlyalpha_http_server.main import main

from tests.runtime_generation_process_support import only_allow_unsealed_test_process_generation

if __name__ == "__main__":
    only_allow_unsealed_test_process_generation()
    raise SystemExit(main())
