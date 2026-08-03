"""UTF-8 JSON Lines observation sink."""

import json
from pathlib import Path

from .models import OnlyMarketObservationSnapshot


class OnlyJsonLinesObservationSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
