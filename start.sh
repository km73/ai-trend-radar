#!/bin/bash
# 一键启动：FastAPI 服务 + cloudflared 公网隧道（沙箱/本地调试用）
# 用法: bash start.sh
set -e
cd "$(dirname "$0")"

# 优先使用能正常 import 的 Python 解释器
PY=$(command -v /root/.pyenv/versions/3.11.1/bin/python3 || command -v python3)

pkill -x cloudflared 2>/dev/null || true
nohup "$PY" app.py > server.log 2>&1 &
echo "✓ server pid $!"

sleep 4

# 注册 cloudflared 快速隧道（带重试，规避偶发限流）
for i in $(seq 1 6); do
  nohup cloudflared tunnel --url http://localhost:8787 --protocol http2 > tunnel.log 2>&1 &
  U=""
  for s in $(seq 1 15); do
    sleep 1
    U=$(grep -o 'https://[a-z0-9]*\.trycloudflare\.com' tunnel.log | grep -v api.trycloudflare | tail -1)
    [ -n "$U" ] && break
  done
  if [ -n "$U" ]; then
    echo "✓ 公网地址: $U"
    break
  fi
  pkill -x cloudflared 2>/dev/null || true
  sleep 3
  echo "  隧道注册重试 $i ..."
done
