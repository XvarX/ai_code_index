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
        print(f"🚀 启动 MCP 服务器: {' '.join(self.mcp_command)}")
        self.process = subprocess.Popen(
            self.mcp_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',  # 明确使用 UTF-8 编码
            errors='replace',  # 遇到无法解码的字符时替换而不是报错
            bufsize=0  # 无缓冲，实时交互
        )
        print("✅ MCP 服务器已启动")

    def stop(self):
        """停止 MCP 服务器"""
        if self.process:
            self.process.stdin.close()
            self.process.terminate()
            self.process.wait()
            print("⏹️  MCP 服务器已停止")

    def send_request(self, method: str, params: Dict[str, Any] = None) -> Dict:
        """
        发送 JSON-RPC 请求到 MCP 服务器

        Args:
            method: MCP 方法名（如 tools/call, tools/list 等）
            params: 方法参数

        Returns:
            服务器响应
        """
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": str(self.request_id),
            "method": method,
            "params": params or {}
        }

        request_str = json.dumps(request) + "\n"
        print(f"\n📤 发送请求 [{method}]:")
        print(f"   {json.dumps(params, ensure_ascii=False, indent=2)}")

        try:
            # 发送请求
            self.process.stdin.write(request_str)
            self.process.stdin.flush()

            # 读取响应
            response_line = self.process.stdout.readline()
            if not response_line:
                raise ConnectionError("MCP 服务器未响应")

            response = json.loads(response_line.strip())

            if "error" in response:
                print(f"❌ 错误: {response['error']}")
                return response

            print(f"📥 收到响应:")
            if "result" in response:
                result = response["result"]
                # 美化输出结果
                if isinstance(result, dict):
                    print(f"   {json.dumps(result, ensure_ascii=False, indent=2)}")
                else:
                    print(f"   {result}")

            return response

        except Exception as e:
            print(f"❌ 请求失败: {e}")
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
        print("🤖 MCP Agent 交互模式")
        print("="*60)
        print("可用命令:")
        print("  1. 查询代码: find_function <module> <action> <target>")
        print("  2. 查结构: find_by_struct <struct_name>")
        print("  3. 查模式: find_by_pattern <pattern_type>")
        print("  4. 列工具: list")
        print("  5. 退出: quit/exit")
        print("="*60)

        while True:
            try:
                user_input = input("\n🔍 输入命令: ").strip()

                if not user_input:
                    continue

                if user_input in ["quit", "exit", "q"]:
                    print("👋 再见！")
                    break

                parts = user_input.split()
                cmd = parts[0].lower()

                if cmd == "list":
                    self.list_tools()

                elif cmd == "find_function" and len(parts) >= 4:
                    self.call_tool("find_function", {
                        "module": parts[1],
                        "action": parts[2],
                        "target": parts[3],
                        "keyword": parts[4] if len(parts) > 4 else ""
                    })

                elif cmd == "find_by_struct" and len(parts) >= 2:
                    self.call_tool("find_by_struct", {
                        "struct_name": parts[1],
                        "method_filter": parts[2] if len(parts) > 2 else ""
                    })

                elif cmd == "find_by_pattern" and len(parts) >= 2:
                    self.call_tool("find_by_pattern", {
                        "pattern_type": parts[1],
                        "module": parts[2] if len(parts) > 2 else ""
                    })

                else:
                    print(f"❓ 未知命令: {user_input}")
                    print("   输入 'list' 查看所有工具")

            except KeyboardInterrupt:
                print("\n\n⚠️  中断信号，退出...")
                break
            except Exception as e:
                print(f"❌ 错误: {e}")


def main():
    """主函数"""
    # 🔧 修改这里：配置你的 MCP 服务器启动命令
    # game_server_rag MCP 服务器
    mcp_command = ["python", "C:\\Users\\admin\\game_server_rag\\mcp_server\\server.py"]

    simulator = MCPAgentSimulator(mcp_command)

    try:
        # 启动 MCP 服务器
        simulator.start()

        # 初始化会话
        print("\n🔐 初始化 MCP 会话...")
        init_response = simulator.initialize()
        if "error" in init_response:
            print(f"❌ 初始化失败: {init_response['error']}")
            return

        print("✅ 会话已建立")

        # 列出可用工具
        print("\n📋 获取可用工具列表...")
        simulator.list_tools()

        # 进入交互模式
        simulator.interactive_session()

    finally:
        simulator.stop()


if __name__ == "__main__":
    main()
