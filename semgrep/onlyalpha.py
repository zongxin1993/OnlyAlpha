import os
import random
import time
from datetime import datetime

# ruleid: onlyalpha-xtquant-only-inside-miniqmt-adapter
import xtquant


def violations() -> tuple[object, ...]:
    # ruleid: onlyalpha-domain-no-wall-clock
    now = datetime.now()
    # ruleid: onlyalpha-domain-no-wall-clock
    epoch = time.time()
    # ruleid: onlyalpha-domain-no-global-random
    sample = random.random()
    # ruleid: onlyalpha-domain-no-environment-access
    token = os.getenv("TOKEN")
    return now, epoch, sample, token, xtquant


def deterministic_inputs(now: object, sample: float, token: str) -> tuple[object, float, str]:
    # ok: onlyalpha-domain-no-wall-clock
    # ok: onlyalpha-domain-no-global-random
    # ok: onlyalpha-domain-no-environment-access
    return now, sample, token
