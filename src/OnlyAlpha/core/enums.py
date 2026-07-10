from enum import Enum


class OnlyAlphaInfoType(Enum):
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"


class OnlyAlphaStatus(Enum):
    START = "START"
    RUNNING = "RUNNING"
    STOP = "STOP"
    FAILED = "FAILED"
