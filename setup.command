#!/bin/bash
# 一键安装脚本 —— 在新电脑上双击运行,自动装好 ffmpeg、Python 和所有依赖
# 前提:先装好 Homebrew(见 README / 迁移说明)

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || { echo "❌ 进入目录失败"; read -n1; exit 1; }

if ! command -v brew >/dev/null 2>&1; then
  echo "❌ 没检测到 Homebrew,请先安装(只需一次,复制到终端回车):"
  echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "装完 Homebrew 后,再双击本脚本。"
  echo "按任意键关闭"; read -n1; exit 1
fi

echo "📦 [1/3] 安装 ffmpeg 和 Python 3.12(已装会自动跳过)…"
brew install ffmpeg python@3.12 || { echo "❌ brew 安装失败"; read -n1; exit 1; }

PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
echo "🐍 [2/3] 创建虚拟环境…"
"$PY" -m venv .venv || { echo "❌ 创建虚拟环境失败"; read -n1; exit 1; }

echo "⬇️  [3/3] 安装项目依赖(opencv、rembg、onnxruntime 等,首次较慢)…"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt || { echo "❌ 依赖安装失败,请把上面的红字截图发我"; read -n1; exit 1; }

echo ""
echo "✅ 全部安装完成!以后双击 start.command 即可启动。"
echo "按任意键关闭"; read -n1
