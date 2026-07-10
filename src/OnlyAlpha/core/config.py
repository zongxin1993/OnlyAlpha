from dataclasses import dataclass


class OnlyAlphaConfig:
    name: str


@dataclass
class ClusterConfig(OnlyAlphaConfig):
    pass


@dataclass
class EngineConfig(OnlyAlphaConfig):
    cluster_config_list: list[ClusterConfig]
