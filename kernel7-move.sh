#!/usr/bin/env bash
# kernel7-move.sh — 24.04 上把内核 6.14 换成 7.0（与 Ubuntu 26.04 同款内核），并先修好 Broadcom 网卡驱动
#
# 背景（2026-10-04 实测，都在本机验证过）：
#   * 现装的 broadcom-sta-dkms 6.30.223.271-23ubuntu1.1 在 ≥6.15 内核上编译失败
#     （kbuild 6.15 移除了 EXTRA_CFLAGS，旧 Makefile 还在用 → typedefs.h fatal error）
#     失败点在 /etc/kernel/postinst.d/dkms 钩子里 → 会让【内核包安装失败 + dpkg 半配置】
#   * 新版 -23ubuntu1.3 已带三处修复（ccflags-y / timer_container_of / radio_idx），
#     实测对 6.8.0-100、6.14.0-27、7.0.0-31 三个内核全部编译通过（EXIT=0，wl.ko 生成）
#   * 26.04 自带的是 -29ubuntu1 / -32，同样实测能编译 7.0
#   * GRUB_DEFAULT=saved 且 saved_entry 钉死在 6.14 → 装了 7.0 也不会自动进它，必须显式指定
#   * 只换内核、不换发行版：26.04 与 24.04 的 HWE 都是 7.0.0-31，等于把大版本风险拆成可回滚的一步
#
# 用法：
#   sudo bash ~/scripts/kernel7-move.sh stage1    # ① 换驱动（不动内核，随时可停）
#   sudo bash ~/scripts/kernel7-move.sh stage2    # ② 装 7.0 内核
#   sudo bash ~/scripts/kernel7-move.sh stage3    # ③ 让【下一次】开机进 7.0（一次性，失败再重启回 6.14）
#   --- 重启 ---
#   sudo bash ~/scripts/kernel7-move.sh verify    # ④ 开机后核验（内核/有线/无线/代理三域/服务）
#   sudo bash ~/scripts/kernel7-move.sh stage4    # ⑤ 核验没问题后，把 7.0 设为永久默认
set -euo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kernel7-pkgs"
SOCK=/tmp/sparkle-mihomo-api.sock
DEB="$PKG/broadcom-sta-dkms_6.30.223.271-23ubuntu1.3_all.deb"
SHA_EXPECT="73604cd799c455488bf25568ea00b12ddf77b228f398d006b7d30973f83bdabd"
KVER_META="linux-image-generic-hwe-24.04"

# 目标内核版本【动态推导】，不写死：noble-security 的 HWE 会往前跑（-31 → -34 → …），
# 写死会出现"索引里是 -31、池子里已被 -34 顶掉 → 404"这种坑（已踩过一次）。
derive_kver() {
  local v
  v="$(dpkg-query -W -f='${Version}' "$KVER_META" 2>/dev/null || true)"
  [ -n "$v" ] || v="$(apt-cache policy "$KVER_META" 2>/dev/null | awk '/候选|Candidate/{print $2; exit}')"
  printf '%s' "$v" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+'
}
KVER="$(derive_kver || true)"
GRUB_7="Advanced options for Ubuntu>Ubuntu, with Linux ${KVER}-generic"
GRUB_6="Advanced options for Ubuntu>Ubuntu, with Linux 6.14.0-27-generic"

die() { echo "!! $*" >&2; exit 1; }
hr()  { echo; echo "======== $* ========"; }

require_root() { [ "$(id -u)" -eq 0 ] || die "要用 sudo 跑：sudo bash $0 $*"; }
require_deb() {
  [ -f "$DEB" ] || die "找不到驱动包 $DEB"
  local got; got=$(sha256sum "$DEB" | awk '{print $1}')
  [ "$got" = "$SHA_EXPECT" ] || die "驱动包 sha256 不符（$got）—— 别装，先查文件"
  echo "驱动包校验 OK: $DEB"
}

stage1() {  # ① 换驱动：先解掉过渡包的版本锁，再装修复版
  require_root "$@"; require_deb
  hr "1/3 解除 bcmwl-kernel-source 的版本锁（它把 broadcom-sta-dkms 钉在 -23ubuntu1.1）"
  apt-mark manual broadcom-sta-dkms >/dev/null   # 防止下面连坐把它自动移除
  apt-get remove -y bcmwl-kernel-source || true  # 过渡包，官方说可安全移除
  hr "2/3 安装带修复的 broadcom-sta-dkms -23ubuntu1.3（dkms 会对每个已装内核重建）"
  dpkg -i "$DEB"
  hr "3/3 dkms 状态（期望：6.8.0-100 / 6.14.0-27 都是 installed）"
  dkms status
  apt-get check >/dev/null 2>&1 && echo "apt 依赖自检: OK" || echo "!! apt 依赖自检有告警，跑 apt-get check 看"
  hr "阶段①完成"
  echo "现在 6.14 仍在跑，WiFi 驱动是修复版。确认无误后执行 stage2。"
}

stage2() {  # ② 装 7.0 内核（image+headers+modules 元包 = 之后自动跟 7.0.x 安全更新）
  require_root "$@"
  hr "0/3 刷新 apt 索引（避免'索引里是 -31、池里已被 -34 顶掉'的 404；这一步实测踩过）"
  apt-get update || die "apt update 失败"
  KVER="$(derive_kver || true)"; [ -n "$KVER" ] || die "刷新后仍推不出目标内核版本"
  GRUB_7="Advanced options for Ubuntu>Ubuntu, with Linux ${KVER}-generic"
  hr "1/3 安装 linux-generic-hwe-24.04（= ${KVER}，与 26.04 同款 7.0 内核）"
  apt-get install -y --no-install-recommends linux-generic-hwe-24.04
  hr "2/3 dkms 是否已为 7.0 建好 wl"
  dkms status | sed 's/^/  /'
  if modinfo -k "${KVER}-generic" wl >/dev/null 2>&1; then
    echo "  ✓ ${KVER} 的 wl 模块已就绪"
  else
    echo "  !! ${KVER} 上没建成 wl —— 先别进 7.0，把 dkms status 的输出发我"
  fi
  hr "3/3 内核与 GRUB"
  ls -l "/boot/vmlinuz-${KVER}-generic" || die "没看到 vmlinuz-${KVER}-generic"
  grep -q "menuentry 'Ubuntu, with Linux ${KVER}-generic'" /boot/grub/grub.cfg \
    || die "grub.cfg 里没有 7.0 的启动项"
  echo "  ✓ grub.cfg 里已有 7.0 启动项"
  echo "  注意：GRUB_DEFAULT=saved，当前 saved_entry 仍是 6.14；这一步不会改默认启动项。"
  hr "阶段②完成 → 执行 stage3，然后重启"
}

stage3() {  # ③ 只把【下一次】开机指向 7.0（一次性；下次再重启自动回 6.14）
  require_root "$@"
  grep -q "menuentry 'Ubuntu, with Linux ${KVER}-generic'" /boot/grub/grub.cfg || die "没有 7.0 启动项，先跑 stage2"
  hr "设定下一次开机 = ${KVER}"
  grub-reboot "$GRUB_7"
  grub-editenv list | sed 's/^/  /'
  echo
  echo "  下一次开机进 7.0。若 7.0 起不来 / 有线不通，再重启一次即自动回到 6.14（一次性引导的好处）。"
  echo "  重启命令：sudo reboot"
  echo "  起来后跑：sudo bash ~/scripts/kernel7-move.sh verify"
}

stage4() {  # ⑤ 把 7.0 变成永久默认
  require_root "$@"
  [ "$(uname -r)" = "${KVER}-generic" ] || die "当前不是 ${KVER}（$(uname -r)），先在 verify 通过后再执行"
  hr "把 7.0 设为 GRUB 永久默认"
  grub-set-default "$GRUB_7"
  grub-editenv list | sed 's/^/  /'
  echo
  echo "  回退方法（任何时候）：sudo grub-reboot \"$GRUB_6\" 或 sudo grub-set-default \"$GRUB_6\""
}

verify() {  # ④ 开机后核验
  require_root "$@"
  hr "内核"
  echo "  uname -r = $(uname -r)"
  [ "$(uname -r)" = "${KVER}-generic" ] && echo "  ✓ 已进 7.0" || echo "  !! 还在老内核（stage3 的一次性引导是否生效？）"

  hr "有线 NIC（唯一活链路）"
  ip -br addr show enp7s0 || true
  echo "  operstate = $(cat /sys/class/net/enp7s0/operstate 2>/dev/null)"
  echo "  驱动 = $(basename "$(readlink -f /sys/class/net/enp7s0/device/driver 2>/dev/null)")"
  echo "  --- dmesg r8169 ---"
  dmesg | grep -iE 'r8169|enp7s0' | tail -12 | sed 's/^/  /' || true
  echo "  --- 丢包/错误 ---"
  ip -s link show enp7s0 | tail -4 | sed 's/^/  /'

  hr "无线（BCM43142 / wl）"
  dkms status | sed 's/^/  /'
  modinfo -k "$(uname -r)" wl >/dev/null 2>&1 && echo "  ✓ 当前内核有 wl 模块" || echo "  !! 当前内核没有 wl"
  rfkill list | sed 's/^/  /'

  hr "代理链路（三域，走 7890）"
  for u in "https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=1|OKX" \
           "https://api.telegram.org/|TG" \
           "https://fapi.binance.com/fapi/v1/ping|fapi"; do
    url="${u%%|*}"; name="${u##*|}"
    timeout 20 curl -s -x http://127.0.0.1:7890 -o /dev/null -w "  $name: %{http_code} %{time_total}s\n" "$url" \
      || echo "  $name: FAILED"
  done
  echo "  （TG 根路径 302 = 正常）"
  echo "  --- mihomo GLOBAL（DIRECT = 事故模式）---"
  curl -s --unix-socket "$SOCK" http://localhost/proxies/GLOBAL 2>/dev/null | head -c 300 | sed 's/^/  /' || echo "  取不到（Sparkle 没起？）"

  hr "服务与数据链"
  systemctl is-active cron docker | sed 's/^/  /'
  echo "  --- 最近数据下载 ---"
  tail -3 /home/gyan/freqtrade/logs/download.log 2>/dev/null | sed 's/^/  /' || true
  hr "核验完毕：三项（有线 / 三域 200 / dkms wl）全绿即可跑 stage4 固化 7.0"
}

case "${1:-}" in
  stage1) stage1 "$@" ;;
  stage2) stage2 "$@" ;;
  stage3) stage3 "$@" ;;
  verify) verify "$@" ;;
  stage4) stage4 "$@" ;;
  *) sed -n '2,30p' "$0"; exit 1 ;;
esac
