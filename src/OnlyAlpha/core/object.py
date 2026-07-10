import multiprocessing as mp
from typing import Any

from src.OnlyAlpha.core.config import ClusterConfig, OnlyAlphaConfig
from src.OnlyAlpha.core.enums import OnlyAlphaInfoType, OnlyAlphaStatus


class OnlyAlphaObject:
    name: str

    def __init__(self, config: OnlyAlphaConfig):
        self.name = config.name


class ClusterStatusInfo(OnlyAlphaObject):
    process: mp.Process
    request_queue: mp.Queue
    response_queue: mp.Queue
    status: OnlyAlphaStatus
    config: ClusterConfig

    def __init__(
        self,
        process: mp.Process,
        request_queue: mp.Queue,
        response_queue: mp.Queue,
        status: OnlyAlphaStatus,
        config: ClusterConfig,
    ):
        super().__init__(config)
        self.process = process
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.status = status
        self.config = config
        self.name = f"{config.name}_{self.__class__.__name__}"


class OnlyAlphaInfo:
    info_type: OnlyAlphaInfoType
    request_type: OnlyAlphaStatus
    cluster_id: str
    data: Any = None

    def __init__(self, info_type: OnlyAlphaInfoType, request_type: OnlyAlphaStatus, cluster_id: str, data: Any = None):
        self.info_type = info_type
        self.request_type = request_type
        self.cluster_id = cluster_id
        self.data = data
