"""Linux kernel restrictions for the installed pure algorithm process."""

from __future__ import annotations

import ctypes
import errno
import platform
import resource


class _Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]


class _Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_Filter))]


def restrict() -> str:
    # Architecture is checked by the BPF program itself; unknown ABIs fail closed.
    architecture = platform.machine()
    allowed: tuple[int, ...]
    if architecture == "x86_64":
        audit, allowed = (
            0xC000003E,
            (
                0,
                1,
                3,
                5,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                28,
                39,
                60,
                63,
                72,
                97,
                98,
                100,
                158,
                186,
                202,
                204,
                218,
                228,
                231,
                273,
                302,
                318,
                334,
            ),
        )
    elif architecture == "aarch64":
        audit, allowed = (
            0xC00000B7,
            (
                25,
                29,
                57,
                62,
                63,
                64,
                67,
                80,
                93,
                94,
                96,
                98,
                99,
                113,
                123,
                134,
                135,
                139,
                153,
                160,
                163,
                165,
                172,
                178,
                214,
                215,
                222,
                226,
                233,
                261,
                278,
                293,
            ),
        )
    else:
        raise RuntimeError("CHART_SANDBOX_ARCHITECTURE_UNAVAILABLE")
    libc = ctypes.CDLL(None, use_errno=True)
    filters = [
        _Filter(0x20, 0, 0, 4),
        _Filter(0x15, 1, 0, audit),
        _Filter(0x06, 0, 0, 0x80000000),
        _Filter(0x20, 0, 0, 0),
    ]
    for number in allowed:
        filters += [_Filter(0x15, 0, 1, number), _Filter(0x06, 0, 0, 0x7FFF0000)]
    filters += [_Filter(0x06, 0, 0, 0x00050000 | errno.EPERM)]
    array = (_Filter * len(filters))(*filters)
    program = _Program(len(filters), array)
    for kind, limit in (
        (resource.RLIMIT_CPU, 10),
        (resource.RLIMIT_AS, 2 * 1024**3),
        (resource.RLIMIT_FSIZE, 0),
        (resource.RLIMIT_CORE, 0),
        (resource.RLIMIT_NOFILE, 32),
        (resource.RLIMIT_NPROC, 1),
    ):
        resource.setrlimit(kind, (limit, limit))
    if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise RuntimeError("CHART_SANDBOX_UNAVAILABLE")
    return "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
