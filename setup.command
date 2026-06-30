#!/bin/bash
# 一键安装脚本 —— 在新电脑(Apple 或 Intel 芯片均可)上双击运行
# 会自动安装 Homebrew、ffmpeg、Python 和所有依赖。装好后双击 start.command 即可使用。

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "❌ 进入目录失败"; read -n1; exit 1; }

# --- 1) 确保 Homebrew 已安装 ---
if ! command -v brew >/dev/null 2>&1; then
  echo "🍺 未检测到 Homebrew,开始自动安装(可能需要输入开机密码)…"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # 把 brew 加入本次脚本的环境(Intel 在 /usr/local,Apple 芯片在 /opt/homebrew)
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [ -x /usr/local/bin/brew ]   && eval "$(/usr/local/bin/brew shellenv)"
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "❌ Homebrew 安装失败。请手动安装后重试:"
  echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "按任意键关闭"; read -n1; exit 1
fi

# --- 2) 安装 ffmpeg 和 Python ---
echo "📦 [1/3] 安装 ffmpeg 和 Python 3.12(已装会自动跳过)…"
brew install ffmpeg python@3.12 || { echo "❌ brew 安装失败"; read -n1; exit 1; }

# --- 3) 创建虚拟环境并装依赖 ---
PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
echo "🐍 [2/3] 创建虚拟环境…"
"$PY" -m venv .venv || { echo "❌ 创建虚拟环境失败"; read -n1; exit 1; }

echo "⬇️  [3/3] 安装项目依赖(opencv、rembg、onnxruntime 等,首次较慢)…"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt || { echo "❌ 依赖安装失败,请把上面的红字截图发我"; read -n1; exit 1; }

echo ""
echo "✅ 全部安装完成!现在双击 start.command 即可启动使用。"
echo "按任意键关闭"; read -n1
