#!/bin/bash
# 为 SCIP 索引初始化最小 Git 仓库
# 用法: cd /path/to/testhd && bash ../build/init_git_for_scip.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/testhd"

echo "为 SCIP 初始化 Git 仓库: $PROJECT_DIR"

cd "$PROJECT_DIR" || exit 1

# 如果已经是 Git 仓库，跳过
if [ -d .git ]; then
    echo "✓ 已经是 Git 仓库，跳过"
    exit 0
fi

# 初始化 Git
git init
git add .
git commit -m "Initial commit for SCIP"

echo "✓ Git 仓库初始化完成"
echo ""
echo "后续更新 SCIP 索引时，记得提交代码变更："
echo "  git add ."
echo "  git commit -m 'Update code'"
