from examples.integration_demo.run_all import run_all


def show(scenario_id: str) -> None:
    report = next(item for item in run_all() if item.scenario_id == scenario_id)
    print(f"[{report.scenario_id}] PASS {report.title}: {'; '.join(report.details)}")
