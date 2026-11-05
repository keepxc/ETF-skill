#!/bin/bash
# 输出双投：频道（tg_push/BTC2dayBot，渠道 ID 存在才推）+ stdout（Hermes -> DM）
# 频道 ID 放在 .etf_channel_id（本地文件，不入库），仓库版与本文件保持一致
cd /home/gyan/scripts/etf_skill
out=$(python3 etf_monthly.py); rc=$?
ch=$(cat /home/gyan/.hermes/scripts/.etf_channel_id 2>/dev/null)
if [ -n "$out" ] && [ -n "$ch" ]; then
  printf '%s' "$out" | python3 /home/gyan/.hermes/scripts/tg_push.py --stdin --chat "$ch" \
    || echo "[warn] 频道推送失败（DM 照发）" >&2
fi
[ -n "$out" ] && printf '%s\n' "$out"
exit $rc
