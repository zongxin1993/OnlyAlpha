from examples.integration_demo.run_all import run_all

if __name__ == "__main__":
    for report in run_all():
        print(f"[{report.scenario_id}] PASS {report.title}")
