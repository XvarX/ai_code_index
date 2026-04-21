# 跨机器部署问题修复总结

## 问题描述

在新机器上运行时，MCP 服务器无法启动，报错"MCP 服务器未响应"或"Connection refused"。

## 根本原因

配置文件中使用**硬编码的绝对路径**，导致跨机器部署失败：

1. `config.yaml`: `root: "C:\\Users\\admin\\game_server_rag\\testhd"`
2. `mcp_agent_simulator.py`: `mcp_command = ["python", "C:\\Users\\admin\\...\\server.py"]`

## 修复方案

### 1. 配置文件支持环境变量和相对路径

**修复前**：
```yaml
root: "C:\\Users\\admin\\game_server_rag\\testhd"
```

**修复后**：
```yaml
root: "${GAME_SERVER_ROOT:-./testhd}"  # 支持环境变量或相对路径
```

### 2. 创建配置加载辅助函数

新增 `utils/config_helper.py`，提供以下功能：
- 展开环境变量（`${VAR:-default}` 语法）
- 解析相对路径（相对于配置文件所在目录）
- 自动转换为绝对路径

### 3. 更新所有配置加载代码

修复的文件：
- ✅ `build/build_all.py`
- ✅ `mcp_server/server.py`
- ✅ `mcp_agent_simulator.py`

### 4. 自动路径检测

`mcp_agent_simulator.py` 现在自动检测服务器路径：
```python
# 自动检测，无需手动配置
server_path = os.path.join(current_dir, "server.py")
```

---

## 使用方式

### 方式 1：默认（推荐）

直接运行，使用相对路径：

```bash
cd build
python build_all.py

cd ../mcp_server
python server.py
```

### 方式 2：环境变量

适合生产环境或自定义路径：

```bash
# Windows
set GAME_SERVER_ROOT=D:\path\to\your\project

# Linux/Mac
export GAME_SERVER_ROOT=/path/to/your/project
```

### 方式 3：绝对路径

修改 `config.yaml`：

```yaml
root: "D:\\your\\custom\\path"
```

---

## 快速诊断

运行诊断脚本检查配置：

```bash
python check_setup.py
```

输出示例：
```
[OK] 配置文件: config.yaml
[OK] 构建脚本: build/build_all.py
[OK] MCP 服务器: mcp_server/server.py
[OK] 项目根目录存在: C:\Users\admin\game_server_rag\testhd
```

---

## 新增文件

1. ✅ `utils/config_helper.py` - 配置加载辅助函数
2. ✅ `utils/__init__.py` - 工具包初始化
3. ✅ `check_setup.py` - 快速诊断脚本
4. ✅ `DEPLOYMENT.md` - 部署指南
5. ✅ `requirements.txt` - 更新依赖列表

---

## 迁移步骤

### 从旧机器迁移到新机器

```bash
# 1. 复制整个项目
scp -r game_server_rag user@new-machine:/path/

# 2. 在新机器上安装依赖
cd game_server_rag
pip install -r requirements.txt

# 3. 运行诊断（可选）
python check_setup.py

# 4. 重新构建知识库（路径变了）
cd build
python build_all.py

# 5. 测试
cd ../mcp_server
python mcp_agent_simulator.py
```

### 从当前项目迁移

如果你想修改项目代码目录的名称：

```bash
# 假设想把 testhd 改成 my_project
mv testhd my_project

# 方式 1：设置环境变量
export GAME_SERVER_ROOT=./my_project

# 方式 2：修改 config.yaml
# root: "./my_project"
```

---

## 配置优先级

系统按以下优先级查找项目路径：

1. **环境变量** `GAME_SERVER_ROOT`
2. **相对路径** `./testhd`（相对于 `config.yaml`）
3. **绝对路径**（手动配置）

---

## 常见问题

### Q: 诊断脚本显示 `[FAIL] LSP 客户端`

A: 这是正常的。`lsp_client` 是项目本地模块，不是 pip 包。

### Q: 如何确认配置正确？

A: 运行诊断脚本：
```bash
python check_setup.py
```

### Q: 数据库需要重新构建吗？

A: 如果项目路径改变（迁移到新机器），需要重新构建：
```bash
cd build
python build_all.py
```

---

## 技术细节

### 环境变量语法

支持 `${VAR:-default}` 语法：
- 如果 `VAR` 存在，使用 `VAR` 的值
- 如果 `VAR` 不存在，使用 `default`

示例：
```yaml
root: "${GAME_SERVER_ROOT:-./testhd}"
```

### 路径解析规则

- **相对路径**：相对于 `config.yaml` 所在目录
- **绝对路径**：直接使用
- **环境变量**：展开后按上述规则处理

---

## 总结

✅ **问题已解决**

现在项目支持跨机器部署，无需手动修改配置文件。

**关键改进**：
1. 配置文件支持环境变量和相对路径
2. 自动路径检测，无需硬编码
3. 提供诊断脚本，快速定位问题

**下一步**：
1. 运行 `python check_setup.py` 检查配置
2. 如需重新构建，运行 `cd build && python build_all.py`
3. 启动服务器：`cd mcp_server && python server.py`

详细部署指南请参考 `DEPLOYMENT.md`。
