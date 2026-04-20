"""
search_test.py - 交互式向量搜索测试
输入文本，返回最相关的代码块

用法:
  cd game_server_rag
  python search_test.py
"""

import json
import os
import chromadb
import yaml

# 加载配置
with open('config.yaml', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 初始化
mode = config.get('embedding', {}).get('mode', 'api')

if mode == 'api':
    from openai import OpenAI
    embed_client = OpenAI(
        api_key=config['embedding']['api_key'],
        base_url=config['embedding']['base_url'],
    )
else:
    embed_client = None

db_client = chromadb.PersistentClient(path=os.path.join('data', 'chroma_db'))
collection = db_client.get_or_create_collection(
    name="game_server_code",
    metadata={"hnsw:space": "cosine"},
)

print(f"知识库中共 {collection.count()} 条记录")
print(f"Embedding 模式: {mode}")
print("输入搜索文本（输入 q 退出）\n")


def build_where(module=None, action=None):
    """构建 ChromaDB where 条件"""
    conditions = {}
    if module:
        conditions['module'] = module
    if action:
        conditions['action'] = action
    return conditions if conditions else None


def search(query, module=None, action=None, n=5):
    where = build_where(module, action)

    kwargs = {
        "n_results": n,
    }
    if where:
        kwargs["where"] = where

    if mode == 'local':
        kwargs["query_texts"] = [query]
    else:
        resp = embed_client.embeddings.create(
            model=config['embedding']['model'],
            input=[query],
        )
        embedding = resp.data[0].embedding
        kwargs["query_embeddings"] = [embedding]

    return collection.query(**kwargs)


def print_results(results):
    if not results["ids"][0]:
        print("  未找到结果\n")
        return

    for i, doc_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        doc = results["documents"][0][i]
        print(f"  [{i+1}] {meta.get('function', '')}")
        print(f"      文件: {meta.get('file', '')}:{meta.get('line', '')}")
        print(f"      模块: {meta.get('module', '')} | 动作: {meta.get('action', '')} | 类: {meta.get('struct', '')}")
        print(f"      描述: {meta.get('description', '')}")
        print(f"      距离: {distance:.4f}")
        code_lines = doc.split('\n')
        preview = '\n'.join(code_lines[:6])
        if len(code_lines) > 6:
            preview += f"\n      ... (共 {len(code_lines)} 行)"
        print(f"      代码预览:\n      {preview}")
        print()


# 交互循环
while True:
    try:
        query = input("搜索> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n退出")
        break

    if query.lower() == 'q':
        break
    if not query:
        continue

    module = None
    action = None
    parts = query.split()
    remaining = []
    for p in parts:
        if p.startswith('module:'):
            module = p.split(':', 1)[1]
        elif p.startswith('action:'):
            action = p.split(':', 1)[1]
        else:
            remaining.append(p)

    search_text = ' '.join(remaining) if remaining else query

    filters = []
    if module:
        filters.append(f"模块={module}")
    if action:
        filters.append(f"动作={action}")
    filter_str = f" (过滤: {', '.join(filters)})" if filters else ""

    print(f"  搜索: \"{search_text}\"{filter_str}\n")
    results = search(search_text, module=module, action=action)
    print_results(results)
