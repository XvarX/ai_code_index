@echo off
REM 为 SCIP 索引初始化最小 Git 仓库
REM 用法: cd C:\path\to\testhd && ..\build\init_git_for_scip.bat

set PROJECT_DIR=%~dp0..\testhd

echo 为 SCIP 初始化 Git 仓库: %PROJECT_DIR%

cd /d "%PROJECT_DIR%" || exit /b 1

REM 如果已经是 Git 仓库，跳过
if exist .git (
    echo ✓ 已经是 Git 仓库，跳过
    exit /b 0
)

REM 初始化 Git
git init
git add .
git commit -m "Initial commit for SCIP"

echo ✓ Git 仓库初始化完成
echo.
echo 后续更新 SCIP 索引时，记得提交代码变更：
echo   git add .
echo   git commit -m "Update code"
