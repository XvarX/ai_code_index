"""
embedder.py - 向量化入库
通过 OpenAI 兼容 API 调用向量模型生成 Embedding，存入 ChromaDB
"""

import os
import chromadb
from openai import OpenAI


def get_embedding_client(config):
    """创建 Embedding API 客户端"""
    base_url = config['embedding']['base_url']
    api_key = config['embedding'].get('api_key') or os.getenv('OPENAI_API_KEY')
    print(f"  [Embedding] 连接 {base_url}")
    return OpenAI(api_key=api_key, base_url=base_url)


def batch_embed(client, model, texts, batch_size=16):
    """分批调用 Embedding API"""
    all_embeddings = []
    total = len(texts)

    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        batch = [t if t.strip() else " " for t in batch]

        print(f"  [Embedding] 调用API: 模型={model}, 文本数={len(batch)}...")
        resp = client.embeddings.create(
            model=model,
            input=batch,
        )
        dim = len(resp.data[0].embedding) if resp.data else 0
        print(f"  [Embedding] 返回成功: {len(resp.data)} 条向量, 维度={dim}")

        sorted_data = sorted(resp.data, key=lambda x: x.index)
        for item in sorted_data:
            all_embeddings.append(item.embedding)

    print(f"  [Embedding] 全部完成: {len(all_embeddings)} 条向量")
    return all_embeddings


def embed_and_store(chunks, config):
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')
    db_client = chromadb.PersistentClient(path=db_path)

    # 每次构建覆盖旧数据
    try:
        db_client.delete_collection("game_server_code")
        print("  已清除旧数据")
    except Exception:
        pass

    embed_client = get_embedding_client(config)
    model = config['embedding']['model']

    rows = []

    for chunk in chunks:
        # 根据不同类型选择文本
        chunk_type = chunk.get('type', '')

        if chunk_type == 'class_summary':
            doc_text = chunk.get('text_for_embedding', chunk.get('description', ''))
            doc_text += f"\n类名: {chunk.get('class_name', '')}"
            doc_text += f"\n职责: {chunk.get('responsibility', '')}"
            doc_text += f"\n核心方法: {', '.join(chunk.get('key_methods', []))}"
            doc_text += f"\n方法数量: {chunk.get('method_count', 0)}"

        elif chunk_type == 'module_summary':
            doc_text = chunk.get('text_for_embedding', chunk.get('description', ''))
            doc_text += f"\n职责: {chunk.get('responsibility', '')}"
            if chunk.get('standard_flow'):
                doc_text += f"\n标准流程:\n" + '\n'.join(f"  {step}" for step in chunk['standard_flow'])
            if chunk.get('entry_points'):
                doc_text += f"\n入口: {', '.join(chunk['entry_points'])}"
            doc_text += f"\n核心类: {', '.join(chunk.get('key_classes', []))}"

        else:
            description = chunk.get('description', '')
            file_path = chunk.get('file', '')
            start_line = chunk.get('start_line', '')
            doc_text = f"{description}\n文件: {file_path}\n行号: {start_line}"

        tags = chunk.get('tags', {}) or {}
        patterns = tags.get('patterns', '')
        if isinstance(patterns, list):
            patterns = ','.join(patterns)

        # ID 格式：type:file:line 或 type:name
        if chunk_type in ('class_summary', 'module_summary'):
            chunk_id = f"{chunk_type}:{chunk.get('name', chunk['file'])}"
        else:
            chunk_id = f"{chunk['file']}:{chunk['start_line']}"

        # 构建统一 schema 的行（所有字段都包含，不用的填空字符串）
        row = {
            'id': chunk_id,
            'text': doc_text,
            'vector': None,  # 填充后设置
            # 通用元数据
            'module': tags.get('module') or chunk.get('module_name', '') or '',
            'action': tags.get('action', '') or '',
            'target': tags.get('target', '') or '',
            'struct': tags.get('struct') or chunk.get('class_name') or '',
            'function': tags.get('function') or chunk.get('name') or '',
            'file': chunk.get('file', ''),
            'line': str(chunk.get('start_line', '')),
            'type': chunk_type,
            'description': chunk.get('description', ''),
            'patterns': patterns or '',
            # 类概述字段
            'class_name': '',
            'method_count': '',
            'key_methods': '',
            'responsibility': '',
            # 模块概述字段
            'module_name': '',
            'file_count': '',
            'class_count': '',
            'entry_points': '',
            'key_classes': '',
        }

        # 填充类型特定字段
        if chunk_type == 'class_summary':
            row['class_name'] = chunk.get('class_name', '')
            row['method_count'] = str(chunk.get('method_count', 0))
            row['key_methods'] = ','.join(chunk.get('key_methods', []))
            row['responsibility'] = chunk.get('responsibility', '')

        elif chunk_type == 'module_summary':
            row['module_name'] = chunk.get('module_name', '')
            row['file_count'] = str(chunk.get('file_count', 0))
            row['class_count'] = str(chunk.get('class_count', 0))
            row['entry_points'] = ','.join(chunk.get('entry_points', []))
            row['key_classes'] = ','.join(chunk.get('key_classes', []))

        rows.append(row)

    # 调用 Embedding API
    print(f"  开始向量化 {len(rows)} 条文本...")
    embeddings = batch_embed(embed_client, model, [r['text'] for r in rows])

    # 填充向量
    for row, emb in zip(rows, embeddings):
        row['vector'] = emb

    # 入库（分批添加，ChromaDB 限制最大批次 5461）
    collection = db_client.get_or_create_collection(
        name="game_server_code",
        metadata={"hnsw:space": "cosine"},
    )

    max_batch_size = 5461
    total = len(rows)
    for i in range(0, total, max_batch_size):
        batch = rows[i:i + max_batch_size]
        collection.add(
            ids=[r['id'] for r in batch],
            documents=[r['text'] for r in batch],
            embeddings=[r['vector'] for r in batch],
            metadatas=[{k: v for k, v in r.items() if k not in ('id', 'text', 'vector')} for r in batch],
        )
        print(f"  已添加 {min(i + max_batch_size, total)}/{total} 条记录")

    # 验证
    count = collection.count()
    print(f"  入库完成: ChromaDB中共 {count} 条记录")

    # 统计各类型数量
    type_stats = {}
    for row in rows:
        t = row.get('type', 'unknown')
        type_stats[t] = type_stats.get(t, 0) + 1
    print(f"  类型统计: {type_stats}")

    return collection


def get_collection(config):
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')
    db_client = chromadb.PersistentClient(path=db_path)
    return db_client.get_or_create_collection(
        name="game_server_code",
        metadata={"hnsw:space": "cosine"},
    )


if __name__ == '__main__':
    import json
    import yaml
    import os

    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')

    # 加载所有 chunks（函数 + 类 + 模块）
    with open(os.path.join(data_dir, 'described_chunks.json'), 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    with open(os.path.join(data_dir, 'class_summaries.json'), 'r', encoding='utf-8') as f:
        class_summaries = json.load(f)

    with open(os.path.join(data_dir, 'module_summaries.json'), 'r', encoding='utf-8') as f:
        module_summaries = json.load(f)

    # 合并所有 chunks
    all_chunks = chunks + class_summaries + module_summaries

    print(f"加载了 {len(chunks)} 个函数, {len(class_summaries)} 个类, {len(module_summaries)} 个模块")
    print(f"总共 {len(all_chunks)} 条记录准备入库...")

    # 向量化入库
    embed_and_store(all_chunks, config)
