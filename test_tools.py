"""测试所有 MCP 工具的正确性（基于 rag_dirs 配置的实际索引范围）"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "utils"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))

from config_helper import load_config
from scip_index import SCIPIndex
from rag_search import RAGSearcher

config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
config = load_config(config_path)

print(f"项目根目录: {config['project']['root']}")
print(f"rag_dirs: {config['project'].get('rag_dirs')}")
print()

scip_path = os.path.join(os.path.dirname(__file__), "data", "index.scip")
scip = SCIPIndex.from_file(
    scip_path,
    config["project"]["root"],
    rag_dirs=config["project"].get("rag_dirs"),
)
rag = RAGSearcher(config)

PASS = 0
FAIL = 0


def test(name, result_str):
    global PASS, FAIL
    try:
        data = json.loads(result_str)
    except Exception:
        data = result_str

    if isinstance(data, dict) and "error" in data:
        FAIL += 1
        print(f"  FAIL  {name}: {data['error']}")
    elif isinstance(data, list) and len(data) == 0:
        FAIL += 1
        print(f"  FAIL  {name}: 返回空数组")
    else:
        PASS += 1
        preview = json.dumps(data, ensure_ascii=False)[:150]
        print(f"  PASS  {name}")
        print(f"        -> {preview}")


def check_path_slashes(name, result_str):
    """验证返回路径全部是正斜杠"""
    data = json.loads(result_str)
    items = data if isinstance(data, list) else [data]
    bad = []
    for item in items:
        if isinstance(item, dict):
            for key in ("file",):
                f = item.get(key, "")
                if "\\" in f:
                    bad.append(f"{key}={f}")
    return bad


# ============================================================
print("=" * 60)
print("第一层：符号搜索")
print("=" * 60)

test("search_symbol MonsterManager (class)",
     scip.search_symbol("MonsterManager", "class"))

test("search_symbol SceneManager (class)",
     scip.search_symbol("SceneManager", "class"))

test("search_symbol spawn_monster (method)",
     scip.search_symbol("MonsterManager.spawn_monster", "method"))

test("search_symbol create_scene (function)",
     scip.search_symbol("SceneManager.create_scene", "method"))

test("search_symbol 不存在的符号",
     scip.search_symbol("NotExist"))

print()
test("module_overview game/manager",
     scip.module_overview("game/manager"))

print()
test("find_inheritance 不在 rag_dirs 内 (CBoss)",
     scip.find_inheritance("CBoss", "parent"))

# ============================================================
print()
print("=" * 60)
print("第二层：代码导航 (SCIP)")
print("=" * 60)

# 用 search_symbol 拿到有效坐标
sym_result = json.loads(scip.search_symbol("MonsterManager", "class"))
if sym_result:
    sample_file = sym_result[0]["file"]
    sample_line = sym_result[0]["line"]
    print(f"  (测试坐标: {sample_file}:{sample_line})")

    test("goto_definition MonsterManager",
         scip.get_definition(sample_file, sample_line))

    test("find_references MonsterManager",
         scip.find_references(sample_file, sample_line))

    test("get_call_chain outgoing",
         scip.get_call_chain(sample_file, sample_line, "outgoing"))

    test("get_call_chain incoming",
         scip.get_call_chain(sample_file, sample_line, "incoming"))
else:
    FAIL += 4
    print("  SKIP  无法获取测试坐标")

# ============================================================
print()
print("=" * 60)
print("第三层：语义搜索 (RAG)")
print("=" * 60)

test("search_by_type 怪物管理",
     rag.search_by_type("怪物管理"))

test("search_by_type + chunk_type=class_summary",
     rag.search_by_type("管理器", chunk_type="class_summary"))

test("search_by_type + module 过滤",
     rag.search_by_type("创建", module="manager"))

test("search_by_type + chunk_type + module 同时过滤",
     rag.search_by_type("创建场景", chunk_type="function", module="manager"))

test("find_class_summary MonsterManager",
     rag.find_class_summary("MonsterManager"))

test("find_module_summary manager",
     rag.find_module_summary("manager"))

# ============================================================
print()
print("=" * 60)
print("备用工具")
print("=" * 60)

if sym_result:
    test("list_symbols",
         scip.list_symbols(sample_file))

test("goto_definition 不存在的文件",
     scip.get_definition("not_exist.py", 1))

# ============================================================
print()
print("=" * 60)
print("路径格式验证（全部应为正斜杠）")
print("=" * 60)

path_results = [
    ("search_symbol", scip.search_symbol("MonsterManager", "class")),
    ("find_references", scip.find_references(sample_file, sample_line) if sym_result else '{"error":"skip"}'),
    ("get_call_chain", scip.get_call_chain(sample_file, sample_line) if sym_result else '{"error":"skip"}'),
    ("module_overview", scip.module_overview("game/manager")),
    ("list_symbols", scip.list_symbols(sample_file) if sym_result else '{"error":"skip"}'),
]

all_ok = True
for name, result_str in path_results:
    bad = check_path_slashes(name, result_str)
    if bad:
        all_ok = False
        for b in bad:
            print(f"  FAIL  {name}: 反斜杠路径 -> {b}")

if all_ok:
    PASS += 1
    print("  PASS  所有路径均为正斜杠格式")
else:
    FAIL += 1

# ============================================================
print()
print("=" * 60)
total = PASS + FAIL
print(f"结果: {PASS}/{total} 通过", end="")
if FAIL > 0:
    print(f"  ({FAIL} 个失败)")
else:
    print()
print("=" * 60)
