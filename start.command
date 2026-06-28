#!/bin/bash
# 去水印工具 —— 双击启动本地服务并打开浏览器(放在项目目录内,自动定位自身路径)
# 使用完毕:按 Control + C 或关闭窗口即可停止

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "❌ 进入目录失败"; read -n1; exit 1; }

if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "❌ 没找到 .venv 环境(请先创建虚拟环境)"; echo "按任意键关闭"; read -n1; exit 1
fi

echo "🎬 正在启动去水印工具…"
pkill -f "uvicorn server:app" 2>/dev/null
sleep 1
( sleep 2; open "http://127.0.0.1:8000" ) &
echo "✅ 浏览器将自动打开 http://127.0.0.1:8000  (按 Control + C 停止)"
echo "------------------------------------------------------------"
exec "$DIR/.venv/bin/python" -m uvicorn server:app --port 8000
