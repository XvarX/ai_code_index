# 项目规范

## 代码知识库

本项目已接入 **三层架构 RAG 代码知识库**（MCP Server: game_server_rag）。
当需要查找项目中的代码时，优先使用以下 MCP 工具，而不是盲目读文件。

---

## 📋 核心规则

### ✅ 必须遵守

1. **查找代码时必须用 RAG 工具**，不要手动 grep 或逐文件翻
2. **拿到文件位置后，必须用 Read 工具读取完整最新代码**
3. **充分利用每一步返回的 metadata**，避免重复查询
4. **用 SCIP 索引精确定位**，而不是反复查询函数详情

### ❌ 禁止行为

1. **禁止直接使用 Grep/Glob 搜索整个代码库**（除非 RAG 找不到结果并得到用户许可）
2. **禁止直接用 RAG 返回的 code_preview 写代码**（code_preview 可能被截断或不是最新代码）
3. **禁止跳过自然语言搜索直接猜测参数**（会导致查询失败）

---

## 🎯 推荐工作流程

### 方式一：基础查询流程（从模糊到精确）

**适用场景**：你需要查找某个功能的实现，但不知道具体的模块名、类名或函数名

```python
# Step 1: 用自然语言搜索，找到相关模块
search_by_type(query="<功能描述>", chunk_type="module_summary", n_results=3)
# 示例：search_by_type("处理用户登录", "module_summary")
# 返回：相关的模块及其信息（module_name, standard_flow, entry_points, key_classes）

# Step 2: 查模块详情，了解标准流程
find_module_summary(module_name="<模块名>")
# 示例：find_module_summary("auth")
# 返回：标准流程步骤、入口函数、核心类列表

# Step 3: 查类详情，了解职责和方法
find_class_summary(class_name="<类名>")
# 示例：find_class_summary("LoginManager")
# 返回：职责描述、核心方法列表、文件位置、行号

# Step 4: 精确定位函数（如果步骤3的方法列表不够详细）
find_function(module="<模块>", action="<动作>", target="<对象>")
# 示例：find_function("user", "create", "session")
# 返回：具体函数的位置和描述

# Step 5: 读取完整代码
Read("<文件路径>")
# 示例：Read("auth/login.py")
```

---

### 方式二：高效查询流程（推荐）⚡

**核心思想**：充分利用每一步返回的丰富信息，避免重复查询

```python
# ===== Step 1: 自然语言搜索 - 一次性获取模块级信息 =====
result = search_by_type("<功能描述>", "module_summary", n_results=1)

# ✅ 充分利用返回信息（不要忽略这些字段）：
# {
#   "module_name": "<模块名>",          # ← 保存下来，下一步用
#   "standard_flow": ["步骤1", "步骤2"], # ← 已经有流程了，不需要再查模块详情！
#   "entry_points": "<入口函数列表>",    # ← 知道从哪里开始
#   "key_classes": "<核心类列表>"        # ← 知道要查哪些类
# }
# ← 不需要再调用 find_module_summary，因为信息已经完整！

# ===== Step 2: 查类详情 - 获取文件位置和方法列表 =====
result = find_class_summary("<类名>")  # 从 key_classes 中选择

# ✅ 充分利用返回信息：
# {
#   "key_methods": "<方法列表>",  # ← 已经有方法列表了，不需要再查函数！
#   "file": "<文件路径>",          # ← 保存下来，下一步用
#   "line": "<起始行号>"           # ← 知道类在哪个位置
# }
# ← 不需要再调用 find_function，因为方法列表已经列出！

# ===== Step 3: 直接读取代码 + SCIP 定位 =====
Read("<文件路径>")  # 使用上一步返回的 file 字段
goto_definition(file="<文件路径>", line=<行号>)  # 精确定位到方法
```

**性能对比**：
- 基础流程：4 次查询 + 1 次 Read = 5 次操作
- **高效流程：2 次查询 + 1 次 Read = 3 次操作**
- **优化：-40% 操作，-47% 耗时**

---

## 🔧 工具快速参考

### 三层知识库工具

| 层次 | 工具 | 参数 | 返回信息 |
|------|------|------|----------|
| 模块层 | `find_module_summary` | `module_name` | 标准流程、入口点、核心类 |
| 类层 | `find_class_summary` | `class_name` | 职责、核心方法、文件位置 |
| 函数层 | `find_function` | `module`, `action`, `target` | 函数位置、描述 |
| 通用 | `search_by_type` | `query`, `chunk_type` | 相关模块/类/函数列表 |

### 函数级查询工具

| 工具 | 参数 | 用途 |
|------|------|------|
| `find_by_struct` | `struct_name` | 查某个类的所有方法 |
| `find_by_pattern` | `pattern_type` | 按代码模式查找（如"创建流程"） |

### SCIP 精确定位工具

| 工具 | 参数 | 用途 |
|------|------|------|
| `goto_definition` | `file`, `line` | 跳转到函数/类定义 |
| `find_references` | `file`, `line` | 查所有引用位置 |
| `get_call_chain` | `file`, `line`, `direction` | 查调用链（incoming/outgoing） |

---

## 📚 查询模式示例

### 模式 1：查找某个功能的实现
```python
# 场景：用户要求"实现一个定时任务调度功能"

# Step 1: 找相关模块
search_by_type("定时任务", "module_summary")

# Step 2: 查标准流程
find_module_summary("<找到的模块名>")

# Step 3: 查关键类
find_class_summary("<找到的类名>")

# Step 4: 读取代码
Read("<文件路径>")
```

### 模式 2：查找某个函数的调用关系
```python
# 场景：需要了解"某个函数被哪些地方调用了"

# Step 1: 找到函数位置
find_function("<模块>", "<动作>", "<对象>")
# → 返回：file, line

# Step 2: 查所有引用
find_references(file="<文件>", line=<行号>)

# Step 3: 查调用链（了解上下文）
get_call_chain(file="<文件>", line=<行号>, direction="incoming")
```

### 模式 3：查找某个类的所有方法
```python
# 场景：需要了解"某个类提供了哪些功能"

# 方式1：查类概述（推荐）
find_class_summary("<类名>")
# → 返回：职责、核心方法列表

# 方式2：查所有方法（更详细）
find_by_struct("<类名>")
# → 返回：所有方法及其位置
```

---

## 🎯 关键要点

### 返回信息利用清单

每次查询后，**必须检查这些字段**：

#### `search_by_type` 返回：
- ✅ `module_name` - 下一步查模块详情用
- ✅ `standard_flow` - 已经有流程了，不需要再查！
- ✅ `entry_points` - 知道从哪里开始
- ✅ `key_classes` - 知道要查哪些类

#### `find_class_summary` 返回：
- ✅ `key_methods` - 已经有方法列表了，不需要再查函数！
- ✅ `file` - 下一步读取用
- ✅ `line` - 知道类在哪个位置

#### `find_function` 返回：
- ✅ `file` - 下一步读取用
- ✅ `line` - 知道函数在哪一行

### 什么时候可以跳过查询？

✅ **可以跳过 `find_module_summary`**：
- 当 `search_by_type` 已经返回 `standard_flow` 和 `entry_points`

✅ **可以跳过 `find_function`**：
- 当 `find_class_summary` 已经返回 `key_methods`

✅ **可以直接用 Read 读取**：
- 当已经拿到 `file` 和 `line`

---

## ⚠️ 常见错误

### 错误 1：跳过自然语言搜索
```python
# ❌ 错误：直接猜测参数
find_function("scene", "create", "npc")  # 可能找不到！

# ✅ 正确：先用自然语言搜索
search_by_type("创建NPC", "module_summary")
# → 返回正确的模块名和参数
```

### 错误 2：忽略返回信息，重复查询
```python
# ❌ 错误：重复查询
result = search_by_type("处理登录", "module_summary")
# 返回：module_name="auth", standard_flow=[...]
find_module_summary("auth")  # 重复！上一步已经返回了

# ✅ 正确：直接使用返回信息
result = search_by_type("处理登录", "module_summary")
module_name = result["module_name"]
flow = result["standard_flow"]  # 直接使用
```

### 错误 3：用 code_preview 写代码
```python
# ❌ 错误：直接用 RAG 返回的代码片段
result = find_function("user", "create", "session")
# result["code_preview"] 只有前 800 字符，可能被截断！
# 不要直接用这个写代码

# ✅ 正确：用 file 和 line 定位，然后 Read 完整代码
result = find_function("user", "create", "session")
Read(result["file"])  # 读取完整代码
```

---

**核心原则**：RAG 是**定位工具**，不是代码库。用 RAG 找到位置后，**必须用 Read 读取完整最新代码**。
