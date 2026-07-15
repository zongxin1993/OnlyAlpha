python -m pytest tests/<component> -q
python -m pytest tests/integration -q
python examples/integration_demo/run_all.py
python -m pytest tests/integration/test_vertical_slice_replay.py -q
