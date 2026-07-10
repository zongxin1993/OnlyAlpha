import multiprocessing as mp
import uuid

from src.OnlyAlpha.core.config import ClusterConfig
from src.OnlyAlpha.core.object import OnlyAlphaObject


class Cluster(OnlyAlphaObject):
    def __init__(self, config: ClusterConfig):
        self.config = config

    @property
    def id(self) -> str:
        return f"{self.config.name}_{uuid.uuid4()}"

    def run(self, cmd_queue: mp.Queue, resp_queue: mp.Queue):
        pass
