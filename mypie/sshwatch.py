"""SSH 로그인 감시: 파이의 SSH 기록(journalctl)을 따라 읽다가 로그인을 텔레그램으로 알린다. 코인 봇 안에서 따로 돈다.

  - 집 밖(공인 IP)에서 로그인 성공 → 바로 알림
  - 로그인 실패 → 바로 알리지 않고 모아서, 낮 12시와 밤 12시에 반나절치를 한 번에 요약해서 알린다
    (실패가 없던 반나절은 보내지 않는다. 공격 봇이 수백 번 두드려도 알림 폭탄이 안 되게)
  - 집 안(192.168.x.x 등)에서 성공한 로그인은 알리지 않는다 (PC에서 자주 들어오니까)
  - 알림 아래 '🚫 IP 막기' 버튼: 누르면 그 IP가 보내는 걸 파이 방화벽이 전부 버린다 (집 안 IP는 못 막는다).
    막기 도구는 root로 돌아서, 파이에서 한 번만 sudo bash ~/My_Pie/deploy/firewall-setup.sh 로 허락해 둬야 한다

SSH 기록은 adm 그룹이면 sudo 없이 읽을 수 있다 (라즈베리파이 기본 사용자는 adm 그룹).
"""

import ipaddress
import json
import logging
import re
import selectors
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .db import Database
from .timeutil import KST, now_kst

log = logging.getLogger("mypie.ssh")

CURSOR_KEY = "ssh_cursor"     # 어디까지 읽었는지 (재시작하면 그 뒤부터 이어 읽는다)
PENDING_KEY = "ssh_failures"  # 아직 안 알린 실패 (재시작해도 이어서 센다)
MAX_USERS = 3                 # IP마다 요약에 보여줄 시도한 아이디 수
MAX_IPS = 5                   # 요약에 하나씩 보여줄 IP 수
ACCEPTED = re.compile(r"Accepted (\S+) for (\S+) from (\S+) port \d+")
FAILED = (re.compile(r"Failed \S+ for (?:invalid user )?(\S+) from (\S+) port (\d+)"),
          re.compile(r"Invalid user (\S*) from (\S+) port (\d+)"))
METHODS = {"publickey": "키", "password": "비밀번호", "keyboard-interactive/pam": "비밀번호"}
FIREWALL = "/usr/local/sbin/mypie-firewall"  # 막기 도구 (deploy/mypie-firewall, firewall-setup.sh가 설치)
BAN = "ban:"                                 # 'IP 막기' 버튼을 누르면 봇에게 오는 값의 앞부분
SETUP_HINT = ("⚠️ IP를 막을 권한이 아직 없어요. 파이에서 한 번만 이렇게 해 주세요:\n"
              "sudo bash ~/My_Pie/deploy/firewall-setup.sh")


def is_home(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def ban_button(ip: str) -> tuple[str, str]:
    return f"🚫 {ip} 막기", BAN + ip


def firewall(*args: str) -> tuple[int, str]:
    """막기 도구를 sudo로 부른다 (비밀번호 없이 되게 firewall-setup.sh로 허락해 둬야 한다). (종료 코드, 출력).
    -1: 도구가 설치되지 않았다 · 2: 막을 수 없는 IP · 그 밖에 0이 아니면 권한이 없거나 실패."""
    if not Path(FIREWALL).exists():
        return -1, ""
    try:
        r = subprocess.run(["sudo", "-n", FIREWALL, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or r.stderr).strip()


def block_text(ip: str) -> str:
    """'IP 막기' 버튼을 눌렀을 때: 막고 결과를 글로."""
    if is_home(ip):
        return f"🙅 {ip}는 집 안 IP라서 막지 않았어요 (막으면 집에서 못 들어와요)."
    code, out = firewall("block", ip)
    if code == 0:
        return (f"🚫 {out or ip}를 막았어요. 이제 이 IP가 파이로 보내는 건 전부 버려요.\n"
                f"풀려면: /차단해제 {out or ip}")
    if code == 2:
        return "🙅 " + out
    return SETUP_HINT


def firewall_reply(text: str) -> str | None:
    """텔레그램 명령 /차단목록 · /차단해제 IP. 이 명령이 아니면 None."""
    parts = (text or "").strip().split()
    word = parts[0].split("@")[0].lstrip("/").lower() if parts else ""
    if word in ("차단목록", "blocked"):
        code, out = firewall("list")
        if code != 0:
            return SETUP_HINT
        ips = out.split()
        if not ips:
            return "🚫 막은 IP가 없어요. SSH 알림의 '막기' 버튼으로 막을 수 있어요."
        return f"🚫 막은 IP {len(ips)}개\n" + "\n".join(f"· {ip}" for ip in ips) + "\n풀려면: /차단해제 IP"
    if word in ("차단해제", "unblock"):
        if len(parts) < 2:
            return "풀 IP를 같이 적어 주세요. 예: /차단해제 45.67.89.20 (목록은 /차단목록)"
        code, out = firewall("unblock", parts[1])
        if code == 0:
            return f"✅ {out or parts[1]}를 풀었어요."
        return ("🙅 " + out) if code == 2 else SETUP_HINT
    return None


def half_day(when: datetime) -> str:
    """실패를 모으는 반나절: '2026-10-22 00' (0~12시) 또는 '2026-10-22 12' (12~24시)."""
    return f"{when.date().isoformat()} {0 if when.hour < 12 else 12:02d}"


class SshWatch:
    def __init__(self, notify, now=now_kst):
        self.notify, self.now = notify, now
        self.pending: dict = {}             # {"period": 반나절, "ips": {IP: {"n": 횟수, "users": [아이디]}}}
        self.seen: deque[str] = deque(maxlen=500)  # 최근 실패한 접속 (IP:포트). 한 접속의 여러 줄은 한 번만 센다

    def handle(self, message: str, when: datetime | None = None) -> None:
        m = ACCEPTED.search(message)
        if m:
            method, user, ip = m.groups()
            if not is_home(ip):
                self.notify(f"🔐 SSH 로그인 · {user} · {ip} ({METHODS.get(method, method)})\n"
                            "내가 아니면 바로 비밀번호를 바꾸고, 아래 버튼으로 이 IP를 막으세요.", [ban_button(ip)])
            return
        for pattern in FAILED:
            m = pattern.search(message)
            if not m:
                continue
            user, ip, port = m.groups()
            if f"{ip}:{port}" in self.seen:
                return
            self.seen.append(f"{ip}:{port}")
            period = half_day(when or self.now())
            if self.pending.get("period") not in (None, period):
                self.summarize(force=True)  # 지난 반나절 것이 남아 있으면 먼저 보낸다
            self.pending.setdefault("period", period)
            x = self.pending.setdefault("ips", {}).setdefault(ip, {"n": 0, "users": []})
            x["n"] += 1
            if user and user not in x["users"] and len(x["users"]) < MAX_USERS:
                x["users"].append(user)
            return

    def summarize(self, force: bool = False) -> bool:
        """반나절(0~12시, 12~24시)이 끝났으면 모아 둔 실패를 한 번에 알린다. 끝난 반나절을 정리했으면 True."""
        period = self.pending.get("period")
        if not period or (period == half_day(self.now()) and not force):
            return False
        ips = self.pending.get("ips") or {}
        if ips:
            day, start = period.split()
            label = f"{int(day[5:7])}/{int(day[8:10])} {int(start):02d}:00~{int(start) + 12:02d}:00"
            top = sorted(ips.items(), key=lambda kv: -kv[1]["n"])
            lines = [f"· {ip}{' (집 안)' if is_home(ip) else ''} {x['n']}번"
                     + (f" ({', '.join(x['users'])})" if x["users"] else "") for ip, x in top[:MAX_IPS]]
            if len(top) > MAX_IPS:
                lines.append(f"· 그 밖에 {len(top) - MAX_IPS}곳 {sum(x['n'] for _, x in top[MAX_IPS:])}번")
            buttons = [ban_button(ip) for ip, _ in top[:MAX_IPS] if not is_home(ip)]
            self.notify(f"⚠️ SSH 로그인 실패 요약 · {label} · 총 {sum(x['n'] for x in ips.values())}번\n" + "\n".join(lines)
                        + ("\n아래 버튼으로 IP를 막을 수 있어요." if buttons else ""), buttons or None)
        self.pending = {}
        return True

    def run(self, db_path, stop_event) -> None:
        """SSH 기록을 계속 따라 읽는다 (journalctl -f). 끊기면 잠시 뒤 다시 붙는다."""
        db = Database(db_path)  # 스레드마다 DB 연결을 따로 연다
        self.pending = db.get_state(PENDING_KEY) or {}
        if firewall("restore")[0] > 0:  # 재부팅하면 방화벽이 비워져서, 막아 둔 IP를 다시 막는다
            log.info("막아 둔 IP를 다시 막지 못했어요 (firewall-setup.sh를 아직 안 했으면 정상)")

        def save(latest):  # 읽은 곳과 모아 둔 실패를 함께 남긴다 (재시작하면 거기서 이어서)
            if latest:
                db.set_state(CURSOR_KEY, latest)
            db.set_state(PENDING_KEY, self.pending)

        while not stop_event.is_set():
            cursor = db.get_state(CURSOR_KEY)
            cmd = ["journalctl", "-t", "sshd", "-t", "sshd-session", "-o", "json", "-f", "--no-pager"]
            cmd += [f"--after-cursor={cursor}"] if cursor else ["-n", "0"]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            except OSError as e:
                log.warning("SSH 기록을 읽지 못했어요: %s", e)
                stop_event.wait(600)
                continue
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            last_save, latest = time.monotonic(), None
            try:
                while not stop_event.is_set() and proc.poll() is None:
                    if selector.select(timeout=30):
                        line = proc.stdout.readline()
                        if not line:
                            break
                        try:
                            entry = json.loads(line)
                        except ValueError:
                            continue
                        latest = entry.get("__CURSOR") or latest
                        stamp = entry.get("__REALTIME_TIMESTAMP")  # 기록된 시각 (마이크로초). 늦게 읽어도 맞는 반나절에 센다
                        when = datetime.fromtimestamp(int(stamp) / 1e6, KST) if str(stamp).isdigit() else None
                        self.handle(str(entry.get("MESSAGE", "")), when)
                    if self.summarize() or (latest and time.monotonic() - last_save > 60):
                        save(latest)
                        last_save = time.monotonic()
            finally:
                save(latest)
                proc.kill()
                selector.close()
            stop_event.wait(30)
