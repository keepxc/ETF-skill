#!/bin/bash
# 周报只发频道（2026-11-06 用户要求：DM 不重复）；频道不可用时才回落到 stdout（→ DM）
# 频道 ID 放在 .etf_channel_id（本地文件，不入库），仓库版与本文件保持一致
cd /home/gyan/scripts/etf_skill
out=$(python3 etf_weekly.py); rc=$?
ch=$(cat /home/gyan/.hermes/scripts/.etf_channel_id 2>/dev/null)
if [ -n "$out" ]; then
  if [ -n "$ch" ] && printf '%s' "$out" | python3 /home/gyan/.hermes/scripts/tg_push.py --stdin --chat "$ch" >/dev/null; then
    :   # 频道已收到 → DM 不再重复
  else
    printf '%s\n' "$out"
  fi
fi
exit $rc
