# MCP 服务器日志使用指南

## 概述

已为 MCP 服务器添加详细的日志功能，帮助诊断问题。

---

## 日志位置

日志文件位于：`logs/mcp_server_YYYYMMDD_HHMMSS.log`

每次启动服务器会创建一个新的日志文件。

---

## 快速诊断

### 方法 1：运行测试脚本（推荐）

```bash
cd mcp_server
python test_server.py
```

这会检查：
- ✅ 必要文件是否存在
- ✅ Python 模块是否已安装
- ✅ 服务器能否正常启动

### 方法 2：运行模拟器

```bash
cd mcp_server
python mcp_agent_simulator.py
```

模拟器会显示：
- 服务器启动状态
- 每个请求的详细信息
- 错误信息和堆栈跟踪

---

## 日志内容

### 服务器启动日志

```
2026-04-09 10:30:00 [INFO] ============================================================
2026-04-09 10:30:00 [INFO] MCP 服务器启动中...
2026-04-09 10:30:00 [INFO] ============================================================
2026-04-09 10:30:00 [INFO] 配置文件路径: /path/to/config.yaml
2026-04-09 10:30:00 [INFO] ✓ 配置加载成功
2026-04-09 10:30:00 [INFO]   项目根目录: /path/to/testhd
2026-04-09 10:30:00 [INFO]   项目语言: python
2026-04-09 10:30:00 [INFO] 初始化 RAG 搜索器...
2026-04-09 10:30:01 [INFO] ✓ RAG 搜索器初始化成功
2026-04-09 10:30:01 [INFO] 初始化 LSP 客户端...
2026-04-09 10:30:01 [INFO] ✓ LSP 客户端初始化成功
2026-04-09 10:30:01 [INFO] ✓ FastMCP 实例创建成功
2026-04-09 10:30:01 [INFO] 日志文件: logs/mcp_server_20260409_103001.log
2026-04-09 10:30:01 [INFO] ============================================================
2026-04-09 10:30:01 [INFO] MCP 服务器已就绪，等待请求...
2026-04-09 10:30:01 [INFO] ============================================================
```

### 请求处理日志

```
2026-04-09 10:30:05 [INFO] [调用] find_function(module=scene, action=create, target=npc)
2026-04-09 10:30:05 [INFO] [成功] find_function - 返回结果
```

### 错误日志

```
2026-04-09 10:30:10 [ERROR] [错误] find_function - Collection does not exist
2026-04-09 10:30:10 [ERROR] Traceback (most recent call last):
2026-04-09 10:30:10 [ERROR]   File "server.py", line 123, in find_function
2026-04-09 10:30:10 [ERROR]     ...
```

---

## 常见问题诊断

### 问题 1：配置文件加载失败

**日志**：
```
[ERROR] ✗ 配置加载失败: FileNotFoundError
[ERROR]   配置文件: /path/to/config.yaml
```

**解决**：
1. 检查 `config.yaml` 是否存在
2. 检查路径是否正确
3. 运行 `python check_setup.py` 诊断

### 问题 2：RAG 搜索器初始化失败

**日志**：
```
[ERROR] ✗ RAG 搜索器初始化失败: Collection does not exist
```

**解决**：
1. 数据库未构建，运行：
   ```bash
   cd build
   python build_all.py
   ```

### 问题 3：LSP 客户端初始化失败

**日志**：
```
[ERROR] ✗ LSP 客户端初始化失败: pylsp not found
```

**解决**：
1. 安装 LSP：
   ```bash
   pip install python-lsp-server
   ```

---

## 模拟器增强功能

模拟器现在会显示：

### 启动检查
```
[信息] MCP 服务器路径: C:\...\server.py
[信息] Python 版本: 3.x.x
[信息] 检查依赖...
  [OK] mcp 模块

[信息] 正在启动 MCP 服务器...
[成功] MCP 服务器已启动 (PID: 12345)
```

### 请求跟踪
```
[请求] tools/call
[参数] {
  "name": "find_function",
  "arguments": {
    "module": "scene",
    "action": "create",
    "target": "npc"
  }
}
[响应] 成功
```

### 错误提示
```
[错误] MCP 服务器未响应
[提示] 请检查:
  1. 日志文件: logs/mcp_server_*.log
  2. 配置文件: config.yaml
  3. 数据库是否存在: data/chroma_db
```

---

## 日志级别

日志分为以下级别：

- **INFO**: 正常信息（启动、请求等）
- **WARNING**: 警告（不影响运行）
- **ERROR**: 错误（需要处理）

所有日志都会：
- 输出到终端（实时查看）
- 写入日志文件（事后分析）

---

## 调试流程

### Step 1: 运行测试脚本
```bash
cd mcp_server
python test_server.py
```

### Step 2: 查看日志文件
```bash
# 查看最新日志
ls -lt logs/mcp_server_*.log | head -1

# 查看日志内容
tail -f logs/mcp_server_*.log
```

### Step 3: 使用模拟器测试
```bash
python mcp_agent_simulator.py

# 测试命令
list
find_function scene create npc
quit
```

### Step 4: 检查配置
```bash
cd ..
python check_setup.py
```

---

## 性能监控

日志中包含时间戳，可以用于性能分析：

```
10:30:00 [INFO] [调用] find_function(...)
10:30:01 [INFO] [成功] find_function - 返回结果
```

时间差 = 1 秒（查询耗时）

---

## 总结

现在你有三种方式诊断问题：

1. **自动测试**：`python test_server.py`
2. **交互测试**：`python mcp_agent_simulator.py`
3. **日志分析**：查看 `logs/mcp_server_*.log`

如果遇到问题：
1. 先运行测试脚本
2. 再查看日志文件
3. 检查配置和数据库
4. 参考常见问题解决方案
