@echo off
REM 每周重建 SCIP 索引的脚本
REM 用法: 将此脚本加入 Windows 任务计划程序，每周执行一次

set PROJECT_DIR=C:\Users\admin\game_server_rag
set BUILD_DIR=%PROJECT_DIR%\build

echo ========================================
echo 每周 SCIP 索引重建
echo ========================================
echo 时间: %date% %time%
echo.

REM 进入构建目录
cd /d "%BUILD_DIR%" || exit /b 1

REM Step 1: 提交代码变更（如果有）
echo [1/3] 提交代码变更...
cd "%PROJECT_DIR%\testhd"
git add -A
git commit -m "Weekly code update for SCIP" || echo "没有代码变更需要提交"

REM Step 2: 重建 SCIP 索引
echo.
echo [2/3] 重建 SCIP 索引...
cd "%BUILD_DIR%"
python scip_indexer.py

REM Step 3: 重建完整知识库（可选）
echo.
echo [3/3] 重建知识库...
python build_all.py

echo.
echo ========================================
echo SCIP 索引重建完成！
echo ========================================
echo.
echo 耗时: %time%
pause
