#!/usr/bin/env python3
"""
快速测试 game_server_rag MCP 服务器
用于模拟 agent 交互，帮助调试断连问题
"""

import json
import subprocess


def test_mcp_tool(mcp_command, tool_name, arguments):
    """测试单个 MCP 工具调用"""

    print(f"\n{'='*60}")
    print(f"🧪 测试工具: {tool_name}")
    print(f"📝 参数: {json.dumps(arguments, ensure_ascii=False)}")
    print(f"{'='*60}")

    try:
        # 启动 MCP 进程
        proc = subprocess.Popen(
            mcp_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',  # 明确使用 UTF-8 编码
            errors='replace'  # 遇到无法解码的字符时替换而不是报错
        )

        # 构造 JSON-RPC 请求
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        # 发送请求
        request_json = json.dumps(request) + "\n"
        print(f"📤 发送请求...")

        proc.stdin.write(request_json)
        proc.stdin.flush()

        # 读取响应（设置超时）
        import time
        start_time = time.time()
        timeout = 30  # 30秒超时

        while True:
            if time.time() - start_time > timeout:
                proc.kill()
                print(f"⏰ 超时: {timeout}秒内无响应")
                return None

            # 读取一行
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    print(f"❌ MCP 进程意外退出，退出码: {proc.returncode}")
                    stderr_output = proc.stderr.read()
                    if stderr_output:
                        print(f"❌ 错误输出:\n{stderr_output}")
                    return None
                time.sleep(0.1)
                continue

            try:
                response = json.loads(line.strip())
                print(f"📥 收到响应:")

                if "error" in response:
                    print(f"   ❌ 错误: {response['error']}")
                else:
                    result = response.get("result", {})
                    # 美化输出
                    if isinstance(result, str):
                        try:
                            result_obj = json.loads(result)
                            print(f"   ✅ 结果:\n{json.dumps(result_obj, ensure_ascii=False, indent=4)}")
                        except:
                            print(f"   ✅ 结果: {result}")
                    else:
                        print(f"   ✅ 结果:\n{json.dumps(result, ensure_ascii=False, indent=4)}")

                return response

            except json.JSONDecodeError:
                print(f"⚠️  非JSON响应: {line}")
                continue

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        # 清理进程
        if 'proc' in locals():
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except:
                proc.kill()


def main():
    """主测试函数"""

    # 🔧 配置你的 MCP 服务器启动命令
    # 根据你的实际配置修改这里
    mcp_command = [
        "python",  # 或者 "node"
        "path/to/game_server_rag_server.py"  # 修改为你的 MCP 服务器路径
    ]

    print("🎯 game_server_rag MCP 测试套件")
    print("="*60)

    # 测试用例列表
    test_cases = [
        {
            "name": "查找场景创建函数",
            "tool": "find_function",
            "args": {
                "module": "scene",
                "action": "create",
                "target": "scene",
                "keyword": ""
            }
        },
        {
            "name": "查找 SceneManager 的方法",
            "tool": "find_by_struct",
            "args": {
                "struct_name": "SceneManager",
                "method_filter": ""
            }
        },
        {
            "name": "查找定时任务模式",
            "tool": "find_by_pattern",
            "args": {
                "pattern_type": "定时任务",
                "module": ""
            }
        },
        {
            "name": "查找活动配置结构",
            "tool": "find_config_structure",
            "args": {
                "name": "ActivityConfig",
                "type": "config"
            }
        }
    ]

    # 执行测试
    results = []
    for i, test in enumerate(test_cases, 1):
        print(f"\n\n📍 测试 {i}/{len(test_cases)}: {test['name']}")
        result = test_mcp_tool(mcp_command, test['tool'], test['args'])
        results.append({
            "name": test['name'],
            "success": result is not None and "error" not in result
        })

        # 等待一下再进行下一个测试
        import time
        time.sleep(1)

    # 汇总结果
    print(f"\n\n{'='*60}")
    print("📊 测试汇总")
    print(f"{'='*60}")

    for result in results:
        status = "✅ 通过" if result['success'] else "❌ 失败"
        print(f"{status} - {result['name']}")

    success_count = sum(1 for r in results if r['success'])
    print(f"\n总计: {success_count}/{len(results)} 通过")


if __name__ == "__main__":
    main()
