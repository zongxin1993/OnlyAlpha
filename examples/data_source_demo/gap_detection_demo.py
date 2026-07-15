from examples.data_source_demo.common import make_update
from examples.integration_demo.environment import INSTRUMENT_ID, OnlyIntegrationEnvironment
from onlyalpha.data.enums import OnlyMarketDataQualityFlag
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.processor import OnlyMarketDataGapDetector


def main() -> None:
    env = OnlyIntegrationEnvironment()
    detector = OnlyMarketDataGapDetector({INSTRUMENT_ID: env.calendar})
    source_id = OnlyMarketDataSourceId("demo-gap")
    detector.assess(make_update(env, source_id, 0, 1), False)
    assert OnlyMarketDataQualityFlag.UNEXPECTED_GAP in detector.assess(make_update(env, source_id, 2, 2), False)


if __name__ == "__main__":
    main()
