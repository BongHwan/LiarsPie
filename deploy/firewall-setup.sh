#!/usr/bin/env bash
# 한 번만 실행 (파이에서): sudo bash ~/My_Pie/deploy/firewall-setup.sh
# 텔레그램 SSH 알림의 '🚫 IP 막기' 버튼이 쓰는 도구를 설치하고, 봇이 비밀번호 없이 그 도구 하나만 쓸 수 있게 허락한다.
#   /usr/local/sbin/mypie-firewall   막기 도구 (root만 고칠 수 있게 설치)
#   /etc/sudoers.d/mypie-firewall    봇 사용자가 이 도구만 비밀번호 없이 쓰게
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(id -u)" -ne 0 ]; then
  echo "앞에 sudo를 붙여서 실행해 주세요: sudo bash $0"
  exit 1
fi
user="${SUDO_USER:-}"
if [ -z "$user" ] || [ "$user" = root ]; then
  echo "봇을 돌리는 사용자로 로그인한 뒤 sudo를 붙여서 실행해 주세요."
  exit 1
fi
if ! command -v nft >/dev/null; then
  echo "방화벽 도구(nftables)를 설치하는 중..."
  apt-get install -y nftables
fi

install -o root -g root -m 755 mypie-firewall /usr/local/sbin/mypie-firewall
rule=$(mktemp)
echo "$user ALL=(root) NOPASSWD: /usr/local/sbin/mypie-firewall" > "$rule"
visudo -cf "$rule" >/dev/null
install -o root -g root -m 440 "$rule" /etc/sudoers.d/mypie-firewall
rm -f "$rule"
/usr/local/sbin/mypie-firewall restore

echo "완료! 이제 텔레그램 SSH 알림의 '🚫 IP 막기' 버튼과 /차단목록, /차단해제 명령을 쓸 수 있어요."
