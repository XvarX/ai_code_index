# MCP Agent 模拟器使用说明

## 📁 文件说明

1. **`mcp_agent_simulator.py`** - 完整的交互式模拟器
   - 支持交互式命令输入
   - 可以像 agent 一样与 MCP 服务器对话
   - 支持所有 MCP 工具

2. **`test_game_server_rag.py`** - 自动化测试脚本
   - 预设测试用例
   - 批量测试多个工具
   - 生成测试报告

## 🚀 使用步骤

### 第一步: 找到你的 MCP 服务器启动命令

查看你的 MCP 配置文件，找到 game_server_rag 的启动命令：

```bash
# Windows
cat %USERPROFILE%\.claude\mcp.json

# 或者
cat %USERPROFILE%\.claude\claude_desktop_config.json
```

### 第二步: 修改脚本中的 mcp_command

找到脚本中的这一行，修改为你的实际启动命令：

```python
# 例如你的配置是这样的：
# {
#   "mcpServers": {
#     "game_server_rag": {
#       "command": "python",
#       "args": ["C:/path/to/server.py"]
#     }
#   }
# }

# 那么在脚本中这样配置：
mcp_command = [
    "python",
    "C:/path/to/server.py"
]
```

### 第三步: 运行测试

```bash
# 方式1: 运行自动化测试
python test_game_server_rag.py

# 方式2: 运行交互式模拟器
python mcp_agent_simulator.py
```

## 🔍 交互式模式命令

启动 `mcp_agent_simulator.py` 后，可以使用以下命令：

```
# 查找函数
find_function scene create npc

# 查找结构体
find_by_struct SceneManager

# 查找模式
find_by_pattern 定时任务

# 列出所有工具
list

# 退出
quit
```

## 🐛 调试断连问题

如果 MCP 服务器中途断开，这个模拟器可以帮你：

1. **捕获错误信息** - 会显示服务器的 stderr 输出
2. **测试超时** - 默认30秒超时，可调整
3. **逐个测试** - 可以单独测试每个工具
4. **查看日志** - 可以看到完整的请求响应流程

### 常见问题排查

**问题1: GBK 编码错误** ✅ 已修复
```
'gbk' codec can't decode byte 0xaf in position 325
```
- **原因**: Windows 默认 GBK，MCP 返回 UTF-8
- **解决**: 脚本已添加 `encoding='utf-8'` 和 `errors='replace'`
- **已修复**: 直接使用最新版本脚本即可

**问题2: 连接超时**
- 检查 MCP 服务器是否正常启动
- 查看 `timeout` 参数是否需要调整

**问题3: 进程意外退出**
- 脚本会显示退出码和 stderr 输出
- 可能是代码异常或缺少依赖

**问题4: 长时间运行后断开**
- 可能是内存泄漏
- 可能是连接保活问题
- 用这个脚本可以复现问题

## 📝 示例输出

```
🎯 game_server_rag MCP 测试套件
============================================================

📍 测试 1/4: 查找场景创建函数
============================================================
🧪 测试工具: find_function
📝 参数: {"module": "scene", "action": "create", "target": "scene"}
============================================================
📤 发送请求...
📥 收到响应:
   ✅ 结果:
{
  "file": "scene/manager.py",
  "line": 45,
  "function": "create_scene",
  ...
}
```

## 💡 进阶用法

### 添加自己的测试用例

在 `test_game_server_rag.py` 的 `test_cases` 列表中添加：

```python
{
    "name": "测试XXX",
    "tool": "find_function",
    "args": {
        "module": "xxx",
        "action": "yyy",
        "target": "zzz"
    }
}
```

### 调整超时时间

修改脚本中的 `timeout` 值：

```python
timeout = 60  # 改为60秒
```
