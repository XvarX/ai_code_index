"""
enricher.py - 上下文富化器
为每个代码块补充关联信息，让LLM能看懂
"""


def enrich_chunk(chunk):
    """为单个chunk拼装完整上下文"""
    parts = []

    if chunk.get('module_docstring'):
        cleaned = chunk['module_docstring'].strip('"\'').strip()
        if cleaned:
            parts.append(f"[模块说明] {cleaned}")

    if chunk.get('struct_def'):
        parts.append(f"[所属类]\n{chunk['struct_def']}")

    if chunk.get('docstring'):
        cleaned = chunk['docstring'].strip('"\'').strip()
        if cleaned:
            parts.append(f"[函数文档] {cleaned}")

    parts.append(f"[代码] 文件: {chunk['file']}, 行: {chunk['start_line']}-{chunk['end_line']}")
    parts.append(chunk['code'])

    return '\n\n'.join(parts)


def enrich_all_chunks(chunks):
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk['enriched_text'] = enrich_chunk(chunk)
        if (i + 1) % 50 == 0 or i + 1 == total:
            print(f"  富化进度: {i + 1}/{total}")
    return chunks


if __name__ == '__main__':
    import json
    with open('../data/chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    enriched = enrich_all_chunks(chunks)
    with open('../data/enriched_chunks.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"富化完成: {len(enriched)} 个代码块")
