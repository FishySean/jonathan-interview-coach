#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_NAME="jonathan-coach"

source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "未找到 Conda 环境: $ENV_NAME"
  echo "请先运行: ./setup_env.sh"
  exit 1
fi

conda activate "$ENV_NAME"
python app.py
