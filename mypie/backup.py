"""실행 중인 장부의 SQLite 백업을 만들고 복사본을 다시 열어 검증한다."""

import argparse
import json
import sqlite3
import tempfile
import tomllib
from contextlib import closing
from pathlib import Path

from .config import load_config
from .timeutil import now_kst, ts

LEDGERS = {"general": "mypie.db", "stock": "stock.db"}
SETTINGS = "config.toml"
MANIFEST = "verified.json"
TABLES = {"kv", "trades", "equity_log", "events", "bars"}


def folder(db_path: str) -> Path:
    return Path(db_path).resolve().parent / "backups"


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def verify(snapshot: Path) -> None:
    for filename in LEDGERS.values():
        with closing(_readonly(snapshot / filename)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError(f"{filename} 무결성 검사 실패")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not TABLES <= tables:
                raise ValueError(f"{filename}에서 장부에 필요한 테이블을 찾지 못했어요")
    with (snapshot / SETTINGS).open("rb") as config:
        tomllib.load(config)


def create(cfg: dict) -> Path:
    root = folder(cfg["general"]["db_path"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # 복사와 검증이 끝나기 전에는 웹에서 완료된 백업으로 보이지 않는다.
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=root) as work:
        staging = Path(work) / "snapshot"
        staging.mkdir(mode=0o700)
        for section, filename in LEDGERS.items():
            with closing(_readonly(Path(cfg[section]["db_path"]))) as source, \
                    closing(sqlite3.connect(staging / filename)) as destination:
                source.backup(destination)
                destination.execute("PRAGMA journal_mode=DELETE")
        config = Path(cfg["_path"]).read_bytes() if cfg.get("_path") else b"# Built-in defaults\n"
        (staging / SETTINGS).write_bytes(config)
        verify(staging)
        finished = now_kst()
        (staging / MANIFEST).write_text(json.dumps({"verified_at": ts(finished)}), encoding="utf-8")
        target = root / f"backup-{finished:%Y%m%d-%H%M%S-%f}"
        staging.rename(target)
    return target


def last_success(db_path: str) -> str | None:
    for snapshot in sorted(folder(db_path).glob("backup-*"), reverse=True):
        try:
            manifest = json.loads((snapshot / MANIFEST).read_text(encoding="utf-8"))
            stamp = manifest.get("verified_at") if isinstance(manifest, dict) else None
        except (OSError, ValueError):
            continue
        if isinstance(stamp, str):
            return stamp
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="AntLab 장부·설정 백업 및 검증")
    parser.add_argument("--verify", type=Path, metavar="BACKUP_DIR", help="기존 백업을 다시 열어 확인하는 경로")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            verify(args.verify)
            print(f"백업 검증 성공: {args.verify}")
        else:
            print(f"백업 저장 및 검증 성공: {create(load_config())}")
    except (OSError, ValueError, sqlite3.Error) as e:
        parser.exit(1, f"백업 실패: {e}\n")


if __name__ == "__main__":
    main()
