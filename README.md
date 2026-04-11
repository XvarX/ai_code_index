# Game Server RAG - 三层架构代码知识库

基于 MCP (Model Context Protocol) 的游戏服务器代码知识库，提供智能代码搜索和 LSP 精确定位功能。

## 功能特性

### 三层知识库架构
- **模块层**：标准流程、入口点、核心类
- **类层**：职责描述、核心方法列表
- **函数层**：具体函数实现和位置

### 核心功能
- ✅ 自然语言搜索代码
- ✅ 智能模块检测（支持嵌套子模块）
- ✅ LSP 实时代码分析
- ✅ 跨机器部署支持
- ✅ 详细的日志记录

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 构建知识库

```bash
cd build
python build_all.py
```

### 3. 启动 MCP 服务器

```bash
cd mcp_server
python server.py
```

### 4. 测试查询

```bash
cd mcp_server
python mcp_agent_simulator.py

# 测试命令
search_by_type NPC
find_module_summary gameplay/monster
find_class_summary CMonster3
```

## 项目结构

```
game_server_rag/
├── build/              # 知识库构建流程
├── mcp_server/         # MCP 服务器
├── utils/              # 配置辅助工具
├── data/               # 向量数据库
├── config.yaml         # 配置文件
├── requirements.txt    # 依赖列表
└── testhd/             # 示例项目代码
```

## MCP 工具列表

### 三层知识库查询
- `find_module_summary` - 查找模块标准流程
- `find_class_summary` - 查找类职责和方法
- `search_by_type` - 按类型搜索（支持自然语言）

### 函数级查询
- `find_function` - 按模块/动作/对象查函数
- `find_by_struct` - 按类名查所有方法
- `find_by_pattern` - 按代码模式查找

### LSP 精确定位
- `goto_definition` - 跳转到定义
- `find_references` - 查所有引用
- `get_call_chain` - 查调用链

## 配置说明

### config.yaml

```yaml
project:
  name: "game_server"
  root: "${GAME_SERVER_ROOT:-./testhd}"  # 支持环境变量
  language: "python"

module_analysis:
  force_whole_modules:      # 强制作为整体分析的模块
    - "scene"
    - "network"
  skip_submodules:          # 跳过的子目录
    - "__pycache__"
    - "tests"
  min_files_for_submodule: 2  # 子模块自动检测阈值
```

## Agent 使用指南

详见 [testhd/.claude/CLAUDE.md](testhd/.claude/CLAUDE.md)

**核心原则**：
1. 从模糊到精确的查询策略
2. 充分利用返回信息，避免重复查询
3. 用 Read 工具读取完整最新代码
4. RAG 只用于定位，不用于写代码

## 文档

- [部署指南](DEPLOYMENT.md) - 跨机器部署说明
- [跨机器修复总结](CROSS_MACHINE_FIX.md) - 问题修复记录
- [日志使用指南](mcp_server/LOGGING_GUIDE.md) - 日志诊断
- [三层知识库更新说明](三层知识库更新说明.md) - 功能说明

## 技术栈

- **MCP SDK**: Model Context Protocol
- **ChromaDB**: 向量数据库
- **Python LSP**: 实时代码分析
- **GLM API**: Embedding 和 LLM 服务

## 开发指南

### 构建知识库

```bash
cd build
python build_all.py
```

流程：
1. 代码切块（AST 解析）
2. 元数据标注
3. LLM 生成描述
4. 类概述生成
5. 模块概述生成（LSP 调用分析）
6. 向量化存储

### 测试

```bash
# 快速测试
python check_setup.py

# RAG 测试
cd mcp_server
python test_search.py

# 服务器测试
python test_server.py

# 模拟器测试
python mcp_agent_simulator.py
```

## 常见问题

### Q: MCP 服务器未响应？
A: 检查日志文件 `logs/mcp_server_*.log`，使用 `check_setup.py` 诊断

### Q: 查询找不到结果？
A: 确保已运行 `build/build_all.py` 构建知识库

### Q: 跨机器部署失败？
A: 参考 [DEPLOYMENT.md](DEPLOYMENT.md) 和 [CROSS_MACHINE_FIX.md](CROSS_MACHINE_FIX.md)

## 许可证

本项目仅用于学习和研究目的。

## 联系方式

如有问题请查看文档或提交 Issue。
