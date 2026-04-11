# 跨机器部署指南

## 问题说明

之前的配置文件使用硬编码的绝对路径，导致跨机器部署失败。现在已经修复，支持以下三种配置方式。

## 快速开始（推荐）

### 方式 1：使用相对路径（默认，无需配置）

直接运行即可，`config.yaml` 已配置为使用相对路径：

```bash
# 1. 构建知识库
cd build
python build_all.py

# 2. 启动 MCP 服务器
cd ../mcp_server
python server.py

# 3. 测试（可选）
python mcp_agent_simulator.py
```

### 方式 2：使用环境变量（适合生产环境）

```bash
# Windows
set GAME_SERVER_ROOT=D:\path\to\your\project

# Linux/Mac
export GAME_SERVER_ROOT=/path/to/your/project

# 然后运行
cd build
python build_all.py
```

### 方式 3：修改配置文件（不推荐）

编辑 `config.yaml`，直接指定绝对路径：

```yaml
project:
  root: "D:\\your\\custom\\path"  # 改成你的路径
```

---

## 配置文件说明

### config.yaml

```yaml
project:
  # 支持三种格式：
  # 1. 环境变量：${VAR:-default}
  # 2. 相对路径：./testhd
  # 3. 绝对路径：C:\\path\\to\\project
  root: "${GAME_SERVER_ROOT:-./testhd}"
```

### mcp_agent_simulator.py

已自动检测路径，无需手动配置：

```python
# 自动检测 server.py 的位置
# ✅ 不再需要手动修改路径
```

---

## 修复文件清单

以下文件已更新，支持跨机器部署：

1. ✅ `config.yaml` - 使用环境变量或相对路径
2. ✅ `mcp_agent_simulator.py` - 自动检测服务器路径
3. ✅ `build/build_all.py` - 使用新的配置加载函数
4. ✅ `mcp_server/server.py` - 使用新的配置加载函数
5. ✅ `utils/config_helper.py` - 新增配置加载辅助函数

---

## 故障排查

### 问题 1：MCP 服务器未响应

**原因**：服务器路径配置错误

**解决**：
```bash
# 检查 server.py 是否存在
ls mcp_server/server.py

# 测试启动服务器
cd mcp_server
python server.py
```

### 问题 2：找不到项目代码

**原因**：`config.yaml` 中的 `root` 路径不正确

**解决**：
```bash
# 方式 1：设置环境变量
export GAME_SERVER_ROOT=/your/project/path

# 方式 2：修改 config.yaml 使用绝对路径
# root: "/your/project/path"
```

### 问题 3：数据库不存在

**原因**：没有构建知识库

**解决**：
```bash
cd build
python build_all.py
```

---

## 目录结构要求

确保项目目录结构如下：

```
game_server_rag/
├── build/              # 构建脚本
│   └── build_all.py
├── mcp_server/         # MCP 服务器
│   ├── server.py
│   └── mcp_agent_simulator.py
├── utils/              # 工具函数
│   └── config_helper.py
├── config.yaml         # 配置文件
├── testhd/             # 你的项目代码（可修改名）
└── data/               # 数据库目录（自动生成）
    └── chroma_db/
```

---

## 迁移现有项目

如果你已经有一个项目，需要迁移到新机器：

```bash
# 1. 复制整个项目文件夹
scp -r game_server_rag user@new-machine:/path/

# 2. 在新机器上安装依赖
pip install -r requirements.txt

# 3. 重新构建知识库（因为路径变了）
cd build
python build_all.py

# 4. 测试
cd ../mcp_server
python mcp_agent_simulator.py
```

---

## 技术细节

### 配置加载优先级

1. 环境变量 `GAME_SERVER_ROOT`
2. 相对路径 `./testhd`
3. 绝对路径（手动配置）

### 路径解析规则

- **相对路径**：相对于 `config.yaml` 文件所在目录
- **绝对路径**：直接使用
- **环境变量**：展开后按上述规则处理

---

## 联系支持

如果遇到问题，请检查：
1. Python 版本 >= 3.8
2. 所有依赖已安装（`pip install -r requirements.txt`）
3. 项目目录结构完整
4. 数据库已构建（运行过 `build_all.py`）
