import logging
import multiprocessing as mp
import threading
import time
from typing import Dict

# import schedule
from src.OnlyAlpha.core.cluster import Cluster
from src.OnlyAlpha.core.config import ClusterConfig, EngineConfig
from src.OnlyAlpha.core.enums import OnlyAlphaInfoType, OnlyAlphaStatus
from src.OnlyAlpha.core.object import ClusterStatusInfo, OnlyAlphaInfo, OnlyAlphaObject

logger = logging.getLogger(__name__)


class Engine(OnlyAlphaObject):
    def __init__(self, config: EngineConfig):
        self.config = config

        self.__running = False

        self.cluster_map: Dict[str, ClusterStatusInfo] = {}
        for cluster_config in self.config.cluster_config_list:
            self.add_cluster(cluster_config)

    def add_cluster(self, cluster_config: ClusterConfig):
        request_queue = mp.Queue()
        response_queue = mp.Queue()

        cluster_cls = Cluster(cluster_config)

        request_queue.put(
            OnlyAlphaInfo(
                info_type=OnlyAlphaInfoType.REQUEST,
                request_type=OnlyAlphaStatus.START,
                cluster_id=cluster_cls.id,
                data=cluster_config,
            )
        )

        p = mp.Process(
            target=self._run_cluster_worker,
            args=(cluster_cls, cluster_cls.id, request_queue, response_queue),
            name=f"ClusterWorker-{cluster_cls.id}",
        )
        p.start()

        self.cluster_map[cluster_cls.id] = ClusterStatusInfo(
            process=p,
            request_queue=request_queue,
            response_queue=response_queue,
            status=OnlyAlphaStatus.RUNNING,
            config=cluster_config,
        )

    def _run_cluster_worker(
        self,
        cluster_cls: Cluster,
        cluster_id: str,
        request_queue: mp.Queue,
        response_queue: mp.Queue,
    ):
        try:
            cluster_cls.run(request_queue, response_queue)
        except Exception as e:
            logger.error(f"ClusterWorker-{cluster_id} error: {e}")
            self.cluster_map[cluster_id].status = OnlyAlphaStatus.FAILED
            response_queue.put(
                OnlyAlphaInfo(
                    info_type=OnlyAlphaInfoType.RESPONSE,
                    request_type=OnlyAlphaStatus.FAILED,
                    cluster_id=cluster_id,
                    data=str(e),
                )
            )

    def restart_cluster(self, cluster_config: ClusterConfig):
        pass

    def _timer_loop(self):
        """定时器线程：每天定时推送 TIMER 消息"""
        while self.__running:
            # schedule.run_pending()
            time.sleep(1)

    # ---------- 订单处理与风控（核心） ----------
    def _process_responses(self):
        """主循环中轮询所有策略的响应队列（非阻塞）"""
        for sid, info in self.cluster_map.items():
            resp_q = info.response_queue
            try:
                while True:
                    msg = resp_q.get_nowait()
                    if msg.get("type") == "ERROR":
                        logger.error(f"Cluster {sid} 报告错误: {msg.get('error')}")
                        # 触发重启逻辑
                        self.restart_cluster(info.config)
                    elif "symbol" in msg and "price" in msg:
                        # 拦截订单（风控汇总）
                        self._handle_order(sid, msg)
            except mp.Queue.empty:
                continue

    def run(self):
        logger.info("主引擎启动，开始监控策略...")
        # 启动定时器线程
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()

        # 主循环：监控子进程状态 + 处理响应
        while self.__running:
            # 1. 检查子进程是否意外死亡
            for sid, info in list(self.cluster_map.items()):
                if not info.process.is_alive():
                    logger.info(f"Cluster {sid} 已停止，尝试重启...")
                    self.restart_cluster(info.config)

            self._process_responses()
            time.sleep(0.5)  # 防止CPU空转

        # 清理资源
        for sid, info in self.cluster_map.items():
            info.request_queue.put(
                OnlyAlphaInfo(
                    info_type=OnlyAlphaInfoType.REQUEST,
                    request_type=OnlyAlphaStatus.STOP,
                    cluster_id=sid,
                )
            )
            info.process.join(timeout=3)
        logger.info("引擎已关闭")
