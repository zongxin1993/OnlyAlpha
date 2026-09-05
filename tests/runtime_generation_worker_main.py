"""Test-only Research Worker process with a RuntimeGeneration contract fake."""

from onlyalpha.research.worker_main import main
from tests.runtime_generation_process_support import only_allow_unsealed_test_process_generation

if __name__ == "__main__":
    only_allow_unsealed_test_process_generation()
    raise SystemExit(main())
