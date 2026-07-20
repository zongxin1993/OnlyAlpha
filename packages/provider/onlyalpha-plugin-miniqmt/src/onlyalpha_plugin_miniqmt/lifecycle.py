from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
)


class OnlyMiniQmtLifecycle:
    def __init__(self) -> None:
        self.state = OnlyPluginLifecycleState.CREATED

    def initialize(self) -> None:
        self.state = OnlyPluginLifecycleState.INITIALIZED

    def start(self) -> None:
        self.state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        self.state = OnlyPluginLifecycleState.STOPPED

    def health(self) -> OnlyPluginHealth:
        healthy = self.state in {
            OnlyPluginLifecycleState.CONNECTED,
            OnlyPluginLifecycleState.RUNNING,
        }
        return OnlyPluginHealth(
            OnlyPluginHealthStatus.HEALTHY
            if healthy
            else OnlyPluginHealthStatus.UNKNOWN
        )
