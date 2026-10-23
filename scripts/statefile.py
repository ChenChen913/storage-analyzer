# -*- coding: utf-8 -*-
"""statefile.py —— 状态文件的原子写、损坏隔离与进程锁。

registry.py / apps.py 都直接覆盖写 JSON，进程中断会留下半截文件，两个进程
同时跑还会互相覆盖。这里提供三个最小能力：

- locked(path)    : 跨进程排他锁（Windows 用 msvcrt，其余用 fcntl），同进程可重入
- load_json(...)  : 读取 JSON；损坏时把原文件改名隔离，返回默认值而不是抛异常
- save_json(...)  : 写临时文件 + fsync + os.replace，保证要么旧内容要么新内容

状态文件本身已 gitignore，不参与分发。
"""
import json
import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager

# 可重入标记必须是线程局部的：全局 set 会让同进程的第二个线程误以为已持锁
# 而直接放行，读改写就失去互斥保护。
_HELD = threading.local()


def _key(path):
    return os.path.normcase(os.path.realpath(path))


@contextmanager
def locked(path, timeout=10.0):
    """对 path 加进程锁；同一进程内嵌套调用直接放行。"""
    key = _key(path)
    held = set(getattr(_HELD, "keys", ()))
    if key in held:
        yield
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    f = open(path + ".lock", "a+")
    try:
        _acquire(f, timeout)
        held.add(key)
        _HELD.keys = held
        yield
    finally:
        held.discard(key)
        _HELD.keys = held
        _release(f)
        f.close()


def _acquire(f, timeout):
    if os.name == "nt":
        import msvcrt
        end = time.time() + timeout
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.time() > end:
                    raise TimeoutError("状态文件被其他进程占用：%s" % f.name)
                time.sleep(0.1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _release(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def load_json(path, default):
    """读 JSON。文件不存在或已损坏时返回 default；损坏文件改名保留。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        quarantine = path + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            shutil.move(path, quarantine)
            print("状态文件损坏，已隔离为 %s：%s" % (quarantine, e), file=sys.stderr)
        except OSError:
            print("状态文件损坏且无法隔离：%s" % e, file=sys.stderr)
        return default


def save_json(path, data):
    """原子写：临时文件写完并落盘后再替换目标。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
