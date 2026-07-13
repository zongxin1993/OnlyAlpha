"""No-trading demonstration cluster used by tests and examples."""

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig


class OnlyDemoCluster(OnlyCluster):
    """Minimal cluster which records lifecycle callbacks only."""

    def __init__(self, config: OnlyClusterConfig) -> None:
        super().__init__(config)
        self.started = False

    def on_start(self) -> None:
        self.started = True

    def on_stop(self) -> None:
        self.started = False
