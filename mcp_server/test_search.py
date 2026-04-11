#!/usr/bin/env python3
"""
直接测试 RAG 搜索，不通过 MCP
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'utils'))

from config_helper import load_config
from rag_search import RAGSearcher

print("="*60)
print("RAG 搜索测试")
print("="*60)

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
print(f"\n[1/4] 加载配置: {config_path}")
config = load_config(config_path)
print(f"  项目根目录: {config['project']['root']}")

# 初始化 RAG
print(f"\n[2/4] 初始化 RAG 搜索器...")
start = time.time()
rag = RAGSearcher(config)
print(f"  耗时: {time.time() - start:.2f}秒")

# 测试查询
print(f"\n[3/4] 测试 search_by_type...")
start = time.time()
result = rag.search_by_type("NPC", "", 5)
elapsed = time.time() - start
print(f"  耗时: {elapsed:.2f}秒")
print(f"  结果长度: {len(result)} 字符")

# 解析结果
print(f"\n[4/4] 解析结果...")
try:
    import json
    data = json.loads(result)
    print(f"  结果类型: {type(data)}")
    if isinstance(data, list):
        print(f"  结果数量: {len(data)}")
        if data:
            print(f"  第一个结果: {data[0].get('description', 'N/A')}")
except json.JSONDecodeError as e:
    print(f"  JSON 解析失败: {e}")
    print(f"  原始结果前200字符: {result[:200]}")

print(f"\n{'='*60}")
print(f"测试完成！总耗时: {elapsed:.2f}秒")
print(f"{'='*60}")
