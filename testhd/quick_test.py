#!/usr/bin/env python3
"""快速测试 MCP 服务器是否能启动"""

import subprocess
import json
import sys

def test_mcp():
    """测试 MCP 服务器"""
    print("🚀 启动 MCP 服务器...")

    mcp_command = ["python", r"C:\Users\admin\game_server_rag\mcp_server\server.py"]

    try:
        # 启动服务器
        proc = subprocess.Popen(
            mcp_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        print("✅ 服务器进程已启动 (PID: {})".format(proc.pid))

        # 发送一个简单的初始化请求
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }

        print("\n📤 发送初始化请求...")
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()

        # 等待响应（最多5秒）
        import time
        start = time.time()

        while time.time() - start < 5:
            line = proc.stdout.readline()
            if line:
                print("📥 收到响应:")
                print("   " + line.strip())
                try:
                    response = json.loads(line)
                    if "result" in response:
                        print("\n✅ MCP 服务器工作正常！")
                        return True
                    elif "error" in response:
                        print("\n⚠️  服务器返回错误:")
                        print("   " + json.dumps(response["error"], indent=2))
                except json.JSONDecodeError:
                    pass
            else:
                if proc.poll() is not None:
                    print("\n❌ 服务器进程意外退出")
                    print("   退出码:", proc.returncode)
                    stderr = proc.stderr.read()
                    if stderr:
                        print("   错误输出:", stderr)
                    return False
                time.sleep(0.1)

        print("\n⏰ 超时：5秒内无响应")
        return False

    except Exception as e:
        print("\n❌ 启动失败:", e)
        import traceback
        traceback.print_exc()
        return False

    finally:
        # 清理
        if 'proc' in locals():
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except:
                proc.kill()

if __name__ == "__main__":
    success = test_mcp()
    sys.exit(0 if success else 1)
