"""
embedder.py - 向量化入库
支持两种模式:
  - api: 通过 OpenAI 兼容 API 调用远程向量模型
  - local: 使用 ChromaDB 内置的本地 Embedding (all-MiniLM-L6-v2)
"""

import os
import chromadb


def _get_embed_mode(config):
    return config.get('embedding', {}).get('mode', 'api')


def get_embedding_client(config):
    """创建 Embedding API 客户端（仅 api 模式使用）"""
    base_url = config['embedding']['base_url']
    api_key = config['embedding'].get('api_key') or os.getenv('OPENAI_API_KEY')
    print(f"  [Embedding] 模式=api, 连接 {base_url}")
    from openai import OpenAI
    return OpenAI(api_key=api_key, base_url=base_url)


def batch_embed(client, model, texts, batch_size=16):
    """分批调用 Embedding API（仅 api 模式使用）"""
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


def _build_rows(chunks):
    """从 chunks 构建统一的入库行数据"""
    rows = []
    for chunk in chunks:
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

        if chunk_type in ('class_summary', 'module_summary'):
            chunk_id = f"{chunk_type}:{chunk.get('name', chunk['file'])}"
        else:
            chunk_id = f"{chunk['file']}:{chunk['start_line']}"

        row = {
            'id': chunk_id,
            'text': doc_text,
            'vector': None,
            'module': tags.get('module') or chunk.get('module_name', '') or '',
            'action': tags.get('action') or '',
            'target': tags.get('target') or '',
            'struct': tags.get('struct') or chunk.get('class_name') or '',
            'function': tags.get('function') or chunk.get('name') or '',
            'file': chunk.get('file', ''),
            'line': str(chunk.get('start_line', '')),
            'type': chunk_type,
            'description': chunk.get('description', ''),
            'patterns': patterns or '',
            'class_name': '',
            'method_count': '',
            'key_methods': '',
            'responsibility': '',
            'module_name': '',
            'file_count': '',
            'class_count': '',
            'entry_points': '',
            'key_classes': '',
        }

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
    return rows


def _get_or_create_collection(db_client, mode):
    """获取或创建 collection，local 模式使用默认 embedding function"""
    if mode == 'local':
        return db_client.get_or_create_collection(
            name="game_server_code",
            metadata={"hnsw:space": "cosine"},
        )
    return db_client.get_or_create_collection(
        name="game_server_code",
        metadata={"hnsw:space": "cosine"},
    )


def embed_and_store(chunks, config):
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')
    db_client = chromadb.PersistentClient(path=db_path)

    try:
        db_client.delete_collection("game_server_code")
        print("  已清除旧数据")
    except Exception:
        pass

    mode = _get_embed_mode(config)
    rows = _build_rows(chunks)

    collection = _get_or_create_collection(db_client, mode)

    # 准备公共参数
    ids = [r['id'] for r in rows]
    documents = [r['text'] for r in rows]
    metadatas = [{k: v for k, v in r.items() if k not in ('id', 'text', 'vector')} for r in rows]

    if mode == 'local':
        print(f"  [Embedding] 模式=local, 使用 ChromaDB 内置 Embedding")
        print(f"  开始向量化 {len(rows)} 条文本 (ChromaDB 自动计算)...")
        max_batch_size = 5461
        total = len(rows)
        for i in range(0, total, max_batch_size):
            batch_ids = ids[i:i + max_batch_size]
            batch_docs = documents[i:i + max_batch_size]
            batch_metas = metadatas[i:i + max_batch_size]
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            print(f"  已添加 {min(i + max_batch_size, total)}/{total} 条记录")
    else:
        embed_client = get_embedding_client(config)
        model = config['embedding']['model']
        print(f"  开始向量化 {len(rows)} 条文本...")
        embeddings = batch_embed(embed_client, model, documents)

        max_batch_size = 5461
        total = len(rows)
        for i in range(0, total, max_batch_size):
            batch_ids = ids[i:i + max_batch_size]
            batch_docs = documents[i:i + max_batch_size]
            batch_embs = embeddings[i:i + max_batch_size]
            batch_metas = metadatas[i:i + max_batch_size]
            collection.add(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=batch_embs,
                metadatas=batch_metas,
            )
            print(f"  已添加 {min(i + max_batch_size, total)}/{total} 条记录")

    # 验证
    count = collection.count()
    print(f"  入库完成: ChromaDB中共 {count} 条记录")

    type_stats = {}
    for row in rows:
        t = row.get('type', 'unknown')
        type_stats[t] = type_stats.get(t, 0) + 1
    print(f"  类型统计: {type_stats}")

    return collection


def get_collection(config):
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'chroma_db')
    db_client = chromadb.PersistentClient(path=db_path)
    mode = _get_embed_mode(config)
    return _get_or_create_collection(db_client, mode)


if __name__ == '__main__':
    import json
    import yaml
    import os

    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')

    with open(os.path.join(data_dir, 'described_chunks.json'), 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    with open(os.path.join(data_dir, 'class_summaries.json'), 'r', encoding='utf-8') as f:
        class_summaries = json.load(f)

    with open(os.path.join(data_dir, 'module_summaries.json'), 'r', encoding='utf-8') as f:
        module_summaries = json.load(f)

    all_chunks = chunks + class_summaries + module_summaries

    print(f"加载了 {len(chunks)} 个函数, {len(class_summaries)} 个类, {len(module_summaries)} 个模块")
    print(f"总共 {len(all_chunks)} 条记录准备入库...")

    embed_and_store(all_chunks, config)
