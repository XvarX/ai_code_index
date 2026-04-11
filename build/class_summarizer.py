"""
class_summarizer.py - 类概述生成器
为每个类生成整体功能描述，聚合所有方法信息
"""

import asyncio
import json
import os
from collections import defaultdict
from openai import AsyncOpenAI

CLASS_PROMPT = """\
分析以下Python类的完整定义，输出JSON格式。

[文件] {file}
[类名] {class_name}
[继承] {inherits}
[类文档] {class_docstring}
[类字段]
{fields}

[所有方法及描述]
{methods_summary}

请输出以下JSON（不要markdown代码块）:
{{
  "description": "一句话描述这个类的整体功能",
  "module": "所属模块",
  "patterns": ["代码模式数组，如: 创建流程/事件处理/定时任务/状态机/数据持久化/奖励发放/匹配组队"],
  "key_methods": ["核心方法名列表（3-5个最重要）"],
  "responsibility": "这个类的主要职责是什么"
}}"""


def _group_chunks_by_class(chunks):
    """将所有 chunk 按类分组"""
    class_chunks = defaultdict(lambda: {
        'overview': None,
        'methods': [],
        'file': '',
        'inherits': '',
        'class_docstring': '',
        'fields': [],
    })

    for chunk in chunks:
        class_name = chunk.get('class_name')
        if not class_name:
            continue

        group = class_chunks[class_name]

        # 收集类概览
        if chunk['type'] == 'class_overview':
            group['overview'] = chunk
            group['file'] = chunk['file']
            group['class_docstring'] = chunk.get('docstring', '')

            # 解析继承信息（从 code 中提取）
            code = chunk.get('code', '')
            if 'class ' in code:
                # 提取 class XXX(Base): 中的 Base
                for line in code.split('\n')[:3]:
                    if 'class ' in line and '(' in line:
                        inherit_part = line.split('(')[1].split(')')[0] if ')' in line else ''
                        group['inherits'] = inherit_part.strip() or '无'

        # 收集方法
        elif chunk['type'] in ('method', 'function_part'):
            group['methods'].append(chunk)

    return class_chunks


def _extract_class_fields(overview_chunk):
    """从类概览中提取字段定义"""
    fields = []
    if not overview_chunk:
        return fields

    code = overview_chunk.get('code', '')
    lines = code.split('\n')

    for line in lines:
        stripped = line.strip()
        # 简单识别字段：self.xxx = 或 xxx: type =
        if ('self.' in stripped and '=' in stripped) or (': ' in stripped and '=' in stripped):
            # 排除方法定义
            if not stripped.startswith('def ') and not stripped.startswith('@'):
                fields.append(stripped)

    return fields


async def summarize_class(client, class_name, group, model, max_tokens):
    """为单个类生成概述"""
    # 提取字段
    fields = _extract_class_fields(group['overview'])

    # 汇总所有方法
    methods_summary = []
    for method_chunk in group['methods']:
        method_name = method_chunk['name']
        description = method_chunk.get('description', '（暂无描述）')
        methods_summary.append(f"  - {method_name}: {description}")

    methods_text = '\n'.join(methods_summary) if methods_summary else '  （无方法）'

    # 构建字段文本
    fields_text = '\n'.join(f'  {f}' for f in fields) if fields else '  （无类字段）'

    prompt = CLASS_PROMPT.format(
        file=group['file'],
        class_name=class_name,
        inherits=group['inherits'],
        class_docstring=group['class_docstring'] or '（无文档）',
        fields=fields_text,
        methods_summary=methods_text,
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens + 300,
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()

        # 解析 JSON
        content = content.strip()
        if content.startswith('```'):
            lines = content.split('\n')
            content = '\n'.join(lines[1:])
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)
        return {
            'type': 'class_summary',
            'name': f"{class_name} (类概述)",
            'file': group['file'],
            'description': result.get('description', ''),
            'module': result.get('module', ''),
            'patterns': result.get('patterns', []),
            'key_methods': result.get('key_methods', []),
            'responsibility': result.get('responsibility', ''),
            'method_count': len(group['methods']),
            'class_name': class_name,
            # 用于向量化
            'text_for_embedding': f"{class_name}类: {result.get('description', '')}。职责: {result.get('responsibility', '')}",
        }
    except Exception as e:
        print(f"  ❌ 类 {class_name} 概述生成失败: {e}")
        return {
            'type': 'class_summary',
            'name': f"{class_name} (类概述)",
            'file': group['file'],
            'description': f'{class_name} 类，包含 {len(group["methods"])} 个方法',
            'module': '',
            'patterns': [],
            'key_methods': [m['name'] for m in group['methods'][:5]],
            'responsibility': '',
            'method_count': len(group['methods']),
            'class_name': class_name,
            'text_for_embedding': f"{class_name}类，包含{len(group['methods'])}个方法",
        }


async def summarize_all_classes(chunks, config):
    """为所有类生成概述"""
    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    concurrency = config['llm'].get('concurrency', 2)

    # 按类分组
    class_chunks = _group_chunks_by_class(chunks)
    print(f"发现 {len(class_chunks)} 个类")

    # 并发生成概述
    semaphore = asyncio.Semaphore(concurrency)
    done_count = 0
    done_lock = asyncio.Lock()

    async def process_one(class_name, group):
        nonlocal done_count
        async with semaphore:
            summary = await summarize_class(client, class_name, group, model, max_tokens)

            async with done_lock:
                done_count += 1
                print(f"  [{done_count}/{len(class_chunks)}] {class_name}: {summary['description'][:50]}")

            return summary

    tasks = [process_one(name, group) for name, group in class_chunks.items()]
    class_summaries = await asyncio.gather(*tasks)

    await client.close()
    return [s for s in class_summaries if s]


if __name__ == '__main__':
    import yaml
    with open('../config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open('../data/described_chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    class_summaries = asyncio.run(summarize_all_classes(chunks, config))

    with open('../data/class_summaries.json', 'w', encoding='utf-8') as f:
        json.dump(class_summaries, f, ensure_ascii=False, indent=2)

    print(f"\n类概述生成完成: {len(class_summaries)} 个类")
