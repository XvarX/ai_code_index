#!/usr/bin/env python3
"""
快速测试 MCP 服务器是否正常工作
"""
import os
import sys
import subprocess
import time

def test_server():
    """测试 MCP 服务器"""
    print("="*60)
    print("MCP 服务器快速测试")
    print("="*60)

    # 检查文件
    print("\n[检查] 文件是否存在...")
    files_to_check = [
        ("server.py", "MCP 服务器"),
        ("rag_search.py", "RAG 搜索"),
        ("lsp_client.py", "LSP 客户端"),
        ("../config.yaml", "配置文件"),
        ("../data/chroma_db", "向量数据库"),
    ]

    all_exist = True
    for filepath, desc in files_to_check:
        exists = os.path.exists(filepath)
        status = "[OK]" if exists else "[FAIL]"
        print(f"  {status} {desc}: {filepath}")
        if not exists:
            all_exist = False

    if not all_exist:
        print("\n[错误] 缺少必要文件，请检查项目结构")
        return False

    # 检查 Python 模块
    print("\n[检查] Python 模块...")
    modules = [
        ("mcp", "MCP SDK"),
        ("chromadb", "ChromaDB"),
        ("yaml", "PyYAML"),
    ]

    all_imports = True
    for module, desc in modules:
        try:
            __import__(module)
            print(f"  [OK] {desc}")
        except ImportError:
            print(f"  [FAIL] {desc} (未安装)")
            all_imports = False

    if not all_imports:
        print("\n[错误] 缺少必要模块")
        print("请运行: pip install -r ../requirements.txt")
        return False

    # 尝试启动服务器
    print("\n[测试] 启动 MCP 服务器...")
    try:
        server_process = subprocess.Popen(
            [sys.executable, "server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 等待 2 秒
        time.sleep(2)

        # 检查进程状态
        poll_result = server_process.poll()
        if poll_result is not None:
            # 进程退出了
            stderr_output = server_process.stderr.read()
            print(f"  [FAIL] 服务器启动失败 (退出码: {poll_result})")
            print(f"\n[错误信息]")
            print(stderr_output)
            return False
        else:
            print(f"  [OK] 服务器运行中 (PID: {server_process.pid})")

            # 停止服务器
            server_process.terminate()
            server_process.wait(timeout=5)
            print(f"  [OK] 服务器已停止")

    except Exception as e:
        print(f"  [FAIL] 启动失败: {e}")
        return False

    print("\n[成功] 所有测试通过！")
    print("\n下一步:")
    print("  1. 运行模拟器: python mcp_agent_simulator.py")
    print("  2. 查看日志: logs/mcp_server_*.log")
    return True

if __name__ == "__main__":
    success = test_server()
    sys.exit(0 if success else 1)
