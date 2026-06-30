#!/bin/bash
# 一键安装 + 启动(Apple / Intel 芯片通用)
# 在新电脑「终端」里粘贴下面这一行回车即可:
#   curl -fsSL https://raw.githubusercontent.com/dyllench/qushuiyin/main/install.sh | bash

TARGET="$HOME/Desktop/qushuiyin"
echo "=== 🎬 去水印工具 · 一键安装 ==="

# 1) 确保 Homebrew
if ! command -v brew >/dev/null 2>&1; then
  echo "🍺 安装 Homebrew(可能需要输入开机密码)…"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
if [ -x /usr/local/bin/brew ];   then eval "$(/usr/local/bin/brew shellenv)"; fi
if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Homebrew 未就绪。请关掉终端重新打开后再跑一次本命令。"; exit 1
fi

# 2) ffmpeg + Python
echo "📦 安装 ffmpeg 和 Python 3.12(已装会跳过)…"
brew install ffmpeg python@3.12 || { echo "❌ 安装 ffmpeg/python 失败"; exit 1; }

# 3) 下载项目(自动从 GitHub 拉最新)
echo "⬇️  下载项目到 $TARGET …"
TMP="$(mktemp -d)"
if ! curl -fsSL "https://github.com/dyllench/qushuiyin/archive/refs/heads/main.zip" -o "$TMP/app.zip"; then
  echo "❌ 下载失败,请检查网络。"; exit 1
fi
unzip -q "$TMP/app.zip" -d "$TMP" || { echo "❌ 解压失败"; exit 1; }
[ -d "$TARGET" ] && mv "$TARGET" "$TARGET.bak.$(date +%s)"   # 已存在则先备份,绝不覆盖你的旧数据
mv "$TMP/qushuiyin-main" "$TARGET"
rm -rf "$TMP"

# 4) 虚拟环境 + 依赖
echo "🐍 安装依赖(首次较慢,请耐心等几分钟)…"
PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
cd "$TARGET" || exit 1
"$PY" -m venv .venv || { echo "❌ 创建虚拟环境失败"; exit 1; }
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt || { echo "❌ 依赖安装失败,请把上面的红字截图发我"; exit 1; }

# 5) 直接启动
echo ""
echo "✅ 安装完成!项目位置:$TARGET"
echo "🌐 正在打开浏览器… 以后再启动:双击 $TARGET 文件夹里的 start.command"
echo "（按 Control + C 可停止服务）"
echo "------------------------------------------------------------"
( sleep 2; open "http://127.0.0.1:8000" ) &
exec .venv/bin/python -m uvicorn server:app --port 8000
