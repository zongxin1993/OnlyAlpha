"""Run the production Virtual Broker buy path without synthetic fills."""

from examples.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment


def main() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    env.submit_buy()
    env.fill_buy()
    print(env.final_snapshot())


if __name__ == "__main__":
    main()
