"""Console observation sink."""

import json

from .models import OnlyMarketObservationSnapshot


class OnlyConsoleObservationSink:
    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True))
