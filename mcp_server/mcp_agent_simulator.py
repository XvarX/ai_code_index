#!/usr/bin/env python3
"""
MCP Agent 模拟器
用于模拟 agent 与 MCP 服务器交互，帮助调试和测试
"""

import json
import subprocess
import sys
from typing import Any, Dict
import uuid


class MCPAgentSimulator:
    """MCP Agent 模拟器"""

    def __init__(self, mcp_command: list):
        """
        初始化 MCP 连接

        Args:
            mcp_command: 启动 MCP 服务器的命令列表
            例如: ["node", "path/to/server.js"] 或 ["python", "path/to/server.py"]
        """
        self.mcp_command = mcp_command
        self.process = None
        self.request_id = 0

    def start(self):
        """启动 MCP 服务器进程"""
        print(f"[启动] MCP 服务器: {' '.join(self.mcp_command)}")

        # 检查命令是否存在
        import shutil
        if not shutil.which(self.mcp_command[0]):
            print(f"[错误] 找不到命令: {self.mcp_command[0]}")
            print(f"[提示] 请检查:")
            print(f"  1. Python 是否已安装: python --version")
            print(f"  2. server.py 是否存在: {self.mcp_command[1]}")
            return False

        try:
            self.process = subprocess.Popen(
                self.mcp_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=0
            )
            print(f"[成功] MCP 服务器已启动 (PID: {self.process.pid})")

            # 等待一下，检查进程是否崩溃
            import time
            time.sleep(0.5)

            # 检查进程状态
            poll_result = self.process.poll()
            if poll_result is not None:
                # 进程已经退出
                stderr_output = self.process.stderr.read()
                print(f"[错误] MCP 服务器启动失败 (退出码: {poll_result})")
                print(f"[错误信息] {stderr_output}")
                return False

            return True

        except Exception as e:
            print(f"[错误] 启动失败: {e}")
            return False

    def stop(self):
        """停止 MCP 服务器"""
        if self.process:
            self.process.stdin.close()
            self.process.terminate()
            self.process.wait()
            print("[停止] MCP 服务器已停止")

    def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict:
        """
        发送 JSON-RPC 请求到 MCP 服务器

        Args:
            method: MCP 方法名（如 tools/call, tools/list 等）
            params: 方法参数

        Returns:
            服务器响应
        """
        # 检查进程状态
        if not self.process or self.process.poll() is not None:
            print(f"[错误] MCP 服务器未运行")
            return {"error": "MCP 服务器未运行"}

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": str(self.request_id),
            "method": method,
            "params": params or {}
        }

        request_str = json.dumps(request) + "\n"
        print(f"\n[请求] {method}")
        if params:
            print(f"[参数] {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            # 发送请求
            self.process.stdin.write(request_str)
            self.process.stdin.flush()

            # 读取响应（Windows 兼容方式）
            import time

            # 等待响应，最多 5 秒
            start_time = time.time()
            timeout = 5
            response_line = ""

            while time.time() - start_time < timeout:
                # 尝试读取一行
                line = self.process.stdout.readline()
                if line:
                    response_line = line
                    # 调试：显示原始响应
                    print(f"[调试] 服务器返回: {repr(response_line[:100])}")  # 只显示前100字符
                    break

                # 检查进程是否崩溃
                if self.process.poll() is not None:
                    stderr_output = self.process.stderr.read()
                    raise ConnectionError(f"MCP 服务器崩溃\n{stderr_output}")

                # 短暂等待
                time.sleep(0.01)

            if not response_line:
                raise TimeoutError(f"请求超时 ({timeout}秒)")

            # 尝试解析 JSON
            try:
                response = json.loads(response_line.strip())
            except json.JSONDecodeError as e:
                print(f"[错误] JSON 解析失败: {e}")
                print(f"[调试] 原始响应内容:")
                print(f"  {repr(response_line)}")
                # 如果响应太长，截断显示
                if len(response_line) > 200:
                    print(f"  (前200字符: {repr(response_line[:200])})")
                raise

            if "error" in response:
                print(f"[错误] {response['error']}")
                return response

            print(f"[响应] 成功")
            if "result" in response:
                result = response["result"]
                # 美化输出结果
                if isinstance(result, dict):
                    print(f"{json.dumps(result, ensure_ascii=False, indent=2)}")
                else:
                    print(f"{result}")

            return response

        except TimeoutError as e:
            print(f"[超时] {e}")
            return {"error": str(e)}
        except ConnectionError as e:
            print(f"[连接错误] {e}")
            return {"error": str(e)}
        except Exception as e:
            print(f"[错误] 请求失败: {e}")
            import traceback
            print(f"[堆栈] {traceback.format_exc()}")
            return {"error": str(e)}

    def initialize(self):
        """初始化 MCP 会话"""
        return self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "clientInfo": {
                "name": "mcp-agent-simulator",
                "version": "1.0.0"
            }
        })

    def list_tools(self):
        """列出所有可用的 MCP 工具"""
        return self.send_request("tools/list")

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """调用指定的 MCP 工具"""
        return self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

    def interactive_session(self):
        """交互式会话模式"""
        print("\n" + "="*60)
        print("[MCP Agent] 交互模式")
        print("="*60)
        print("可用命令:")
        print("  【第一层：符号搜索】")
        print("  1. 按名称搜索: search_symbol <name> [kind]")
        print("  2. 模块概览: module_overview <module_path>")
        print("  3. 继承关系: find_inheritance <class_name> [direction]")
        print("  【第二层：代码导航】")
        print("  4. 查引用: find_references <file> <line>")
        print("  5. 调用链: get_call_chain <file> <line> [direction]")
        print("  6. 跳定义: goto_definition <file> <line> [column]")
        print("  【第三层：语义搜索】")
        print("  7. 语义搜索: search_by_type <query> [n_results]")
        print("  8. 类概述: find_class_summary <class_name>")
        print("  9. 模块概述: find_module_summary <module_name>")
        print("  【通用】")
        print("  10. 列工具: list")
        print("  11. 退出: quit/exit")
        print("="*60)
        print("示例:")
        print("  search_symbol CMonster class")
        print("  module_overview gameplay")
        print("  find_references gameplay/monster.py 10")
        print("  get_call_chain gameplay/monster.py 10 incoming")
        print("  find_class_summary CMonster3")
        print("  find_module_summary gameplay/monster")
        print("  search_by_type 怪物管理")
        print("="*60)

        while True:
            try:
                user_input = input("\n[输入] 请输入命令: ").strip()

                if not user_input:
                    continue

                if user_input in ["quit", "exit", "q"]:
                    print("[再见] 退出程序")
                    break

                parts = user_input.split()
                cmd = parts[0].lower()

                if cmd == "list":
                    self.list_tools()

                # ===== 第一层：符号搜索 =====
                elif cmd == "search_symbol" and len(parts) >= 2:
                    self.call_tool("search_symbol", {
                        "name": parts[1],
                        "kind": parts[2] if len(parts) > 2 else ""
                    })

                elif cmd == "module_overview" and len(parts) >= 2:
                    self.call_tool("module_overview", {
                        "module_path": parts[1]
                    })

                elif cmd == "find_inheritance" and len(parts) >= 2:
                    self.call_tool("find_inheritance", {
                        "name": parts[1],
                        "direction": parts[2] if len(parts) > 2 else "parent"
                    })

                # ===== 第二层：代码导航 =====
                elif cmd == "find_references" and len(parts) >= 3:
                    self.call_tool("find_references", {
                        "file": parts[1],
                        "line": int(parts[2])
                    })

                elif cmd == "get_call_chain" and len(parts) >= 3:
                    self.call_tool("get_call_chain", {
                        "file": parts[1],
                        "line": int(parts[2]),
                        "direction": parts[3] if len(parts) > 3 else "outgoing"
                    })

                elif cmd == "goto_definition" and len(parts) >= 3:
                    self.call_tool("goto_definition", {
                        "file": parts[1],
                        "line": int(parts[2]),
                        "column": int(parts[3]) if len(parts) > 3 else 0
                    })

                # ===== 第三层：语义搜索 =====
                elif cmd == "search_by_type" and len(parts) >= 2:
                    self.call_tool("search_by_type", {
                        "query": " ".join(parts[1:-1]) if len(parts) > 2 and parts[-1].isdigit() else " ".join(parts[1:]),
                        "n_results": int(parts[-1]) if parts[-1].isdigit() else 5
                    })

                elif cmd == "find_class_summary" and len(parts) >= 2:
                    self.call_tool("find_class_summary", {
                        "class_name": parts[1]
                    })

                elif cmd == "find_module_summary" and len(parts) >= 2:
                    self.call_tool("find_module_summary", {
                        "module_name": parts[1]
                    })

                else:
                    print(f"[未知] 命令: {user_input}")
                    print("   输入 'list' 查看所有工具")

            except KeyboardInterrupt:
                print("\n\n[中断] 用户中断，退出...")
                break
            except Exception as e:
                print(f"[错误] {e}")


def main():
    """主函数"""
    import os

    # 🔧 自动检测 MCP 服务器路径（支持跨机器）
    # 获取当前脚本所在目录的父目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)

    # MCP server.py 应该在 mcp_server 目录下
    server_path = os.path.join(current_dir, "server.py")

    # 检查文件是否存在
    if not os.path.exists(server_path):
        print(f"[错误] 找不到 MCP 服务器文件：{server_path}")
        print(f"   当前目录：{current_dir}")
        print(f"   请确保 mcp_server/server.py 存在")
        return

    mcp_command = ["python", server_path]
    print(f"[信息] MCP 服务器路径: {server_path}")

    # 检查 Python 版本
    import sys
    print(f"[信息] Python 版本: {sys.version}")

    # 检查依赖
    print(f"[信息] 检查依赖...")
    try:
        import mcp
        print(f"  [OK] mcp 模块")
    except ImportError:
        print(f"  [FAIL] mcp 模块未安装")
        print(f"  [提示] 运行: pip install mcp")
        return

    simulator = MCPAgentSimulator(mcp_command)

    try:
        # 启动 MCP 服务器
        print(f"\n[信息] 正在启动 MCP 服务器...")
        if not simulator.start():
            print(f"\n[错误] MCP 服务器启动失败")
            print(f"[提示] 请检查:")
            print(f"  1. 日志文件: logs/mcp_server_*.log")
            print(f"  2. 配置文件: config.yaml")
            print(f"  3. 数据库是否存在: data/chroma_db")
            return

        # 初始化会话
        print(f"\n[信息] 初始化 MCP 会话...")
        init_response = simulator.initialize()
        if "error" in init_response:
            print(f"[错误] 初始化失败: {init_response.get('error')}")
            return

        print(f"[成功] 会话已建立")

        # 列出可用工具
        print(f"\n[信息] 获取可用工具列表...")
        simulator.list_tools()

        # 进入交互模式
        simulator.interactive_session()

    except KeyboardInterrupt:
        print(f"\n\n[中断] 用户中断")
    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        print(f"[堆栈] {traceback.format_exc()}")
    finally:
        print(f"\n[信息] 正在停止 MCP 服务器...")
        simulator.stop()


if __name__ == "__main__":
    main()
