#!/bin/zsh
# 一键创建 / 更新本项目的 Conda 环境
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_NAME="jonathan-coach"

source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "环境 $ENV_NAME 已存在，正在更新..."
  conda env update -n "$ENV_NAME" -f environment.yml --prune
else
  echo "正在创建环境 $ENV_NAME ..."
  conda env create -f environment.yml
fi

conda activate "$ENV_NAME"

echo ""
echo "环境已就绪: $ENV_NAME"
echo "Python: $(which python)"
echo "Flask:  $(python -c 'import flask; print(flask.__version__)')"
echo ""
echo "启动应用:"
echo "  conda activate $ENV_NAME"
echo "  python app.py"
