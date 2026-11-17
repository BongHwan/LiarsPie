"""같은 장부를 사용하는 매매 봇의 중복 실행을 막는다."""

import errno
import os
from contextlib import contextmanager
from pathlib import Path


def _lock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def bot_lock(db_path: str):
    db = Path(db_path).resolve()
    lock_path = db.with_name(db.name + ".bot.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
    except OSError as e:
        raise SystemExit(f"매매 봇 잠금 파일을 열지 못했어요: {e}") from None
    # 파일을 남겨 둬야 모든 실행이 같은 파일에 잠금을 건다.
    with lock_file:
        try:
            lock_file.seek(0)
            _lock(lock_file.fileno())
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise SystemExit(f"이 장부를 사용하는 매매 봇이 이미 실행 중이에요: {db}") from None
            raise SystemExit(f"매매 봇 잠금을 확인하지 못했어요: {e}") from None
        yield
