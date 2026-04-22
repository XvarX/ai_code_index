"""
class_summarizer.py - 类概述生成器
为每个类生成整体功能描述，聚合所有方法信息
"""

import asyncio
import json
import os
from collections import defaultdict
from openai import AsyncOpenAI
from llm_utils import (
    parse_llm_json, validate_response, estimate_tokens,
    truncate_code, get_model_input_limit,
)

# 响应字段规范
CLASS_STEP1_FIELDS = {
    'important_methods': {'type': list, 'default': []},
}

CLASS_STEP2_FIELDS = {
    'description': {'type': str, 'default': ''},
    'module': {'type': str, 'default': ''},
    'patterns': {'type': list, 'default': []},
    'key_methods': {'type': list, 'default': []},
    'responsibility': {'type': str, 'default': ''},
}

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

CLASS_STEP1_PROMPT = """\
分析以下Python类的方法列表，判断哪些是核心方法。

[类名] {class_name}
[继承] {inherits}
[类文档] {class_docstring}
[类字段]
{fields}

[方法签名列表]
{method_signatures}

请输出JSON（不要markdown代码块）:
{{
  "important_methods": ["方法名1", "方法名2", ...]
}}

选择标准:
1. public方法优先（非_开头）
2. 体现类核心职责的方法
3. 被其他方法频繁调用的方法
4. 选3-5个最重要的，最多不超过8个"""


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
        if ('self.' in stripped and '=' in stripped) or (': ' in stripped and '=' in stripped):
            if not stripped.startswith('def ') and not stripped.startswith('@'):
                fields.append(stripped)

    return fields


def _build_methods_summary(methods):
    """构建方法摘要文本（名称+描述）"""
    lines = []
    for m in methods:
        name = m['name']
        desc = m.get('description', '（暂无描述）')
        lines.append(f"  - {name}: {desc}")
    return '\n'.join(lines) if lines else '  （无方法）'


def _build_method_signatures(methods):
    """构建方法签名文本（只含签名，无描述和代码）"""
    lines = []
    for m in methods:
        code = m.get('code', '')
        # 取 def 行作为签名
        for line in code.split('\n'):
            if 'def ' in line:
                lines.append(f"  {line.strip()}")
                break
        else:
            lines.append(f"  def {m['name']}(...)")
    return '\n'.join(lines) if lines else '  （无方法）'


def _build_fields_text(fields):
    """构建字段文本"""
    return '\n'.join(f'  {f}' for f in fields) if fields else '  （无类字段）'


def _make_class_summary(class_name, group, result):
    """从校验后的结果构建类摘要"""
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
        'text_for_embedding': f"{class_name}类: {result.get('description', '')}。职责: {result.get('responsibility', '')}",
    }


def _make_fallback_summary(class_name, group):
    """生成兜底的类摘要"""
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


async def summarize_class(client, class_name, group, model, max_tokens, input_limit):
    """为单个类生成概述。
    内容在限制内 → 单步发送全部。
    内容超长 → 两步：先筛重要方法，再用重要方法生成摘要。
    """
    fields = _extract_class_fields(group['overview'])
    fields_text = _build_fields_text(fields)
    methods_text = _build_methods_summary(group['methods'])

    prompt = CLASS_PROMPT.format(
        file=group['file'],
        class_name=class_name,
        inherits=group['inherits'],
        class_docstring=group['class_docstring'] or '（无文档）',
        fields=fields_text,
        methods_summary=methods_text,
    )

    # 检查 token 是否超限
    budget = input_limit - max_tokens - 200
    prompt_tokens = estimate_tokens(prompt)

    if prompt_tokens <= budget:
        # 单步：内容在限制内，直接发送
        return await _single_step_class(client, prompt, class_name, group, model, max_tokens)

    # 两步：先筛重要方法
    return await _two_step_class(
        client, class_name, group, fields_text,
        model, max_tokens, input_limit, budget,
    )


async def _single_step_class(client, prompt, class_name, group, model, max_tokens):
    """单步生成类概述"""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens + 300,
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()

        result = parse_llm_json(content)
        if result:
            validated = validate_response(result, CLASS_STEP2_FIELDS)
            if validated and validated.get('description'):
                return _make_class_summary(class_name, group, validated)

    except Exception as e:
        print(f"  ❌ 类 {class_name} 概述生成失败: {e}")

    return _make_fallback_summary(class_name, group)


async def _two_step_class(client, class_name, group, fields_text,
                           model, max_tokens, input_limit, budget):
    """两步生成类概述：先筛重要方法，再用重要方法生成摘要"""

    # ---- Step 1: 筛选重要方法 ----
    signatures_text = _build_method_signatures(group['methods'])

    step1_prompt = CLASS_STEP1_PROMPT.format(
        class_name=class_name,
        inherits=group['inherits'],
        class_docstring=group['class_docstring'] or '（无文档）',
        fields=fields_text,
        method_signatures=signatures_text,
    )

    important_names = []
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': step1_prompt}],
            max_tokens=200,
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()
        result = parse_llm_json(content)
        if result:
            validated = validate_response(result, CLASS_STEP1_FIELDS)
            if validated:
                important_names = validated['important_methods']
    except Exception as e:
        print(f"  ⚠️ 类 {class_name} Step1 筛选失败: {e}")

    # 如果 Step 1 失败，取前5个方法
    if not important_names:
        important_names = [m['name'] for m in group['methods'][:5]]

    # ---- Step 2: 用重要方法生成摘要 ----
    # 过滤出重要方法
    important_methods = [m for m in group['methods'] if m['name'] in important_names]
    if not important_methods:
        important_methods = group['methods'][:5]

    # 逐步添加方法描述直到接近预算
    budget_for_step2 = input_limit - max_tokens - 500
    included_methods = []
    used_tokens = 0

    # 先估算固定部分
    step2_prompt_template = CLASS_PROMPT.format(
        file=group['file'],
        class_name=class_name,
        inherits=group['inherits'],
        class_docstring=group['class_docstring'] or '（无文档）',
        fields=fields_text,
        methods_summary='{placeholder}',
    )
    fixed_tokens = estimate_tokens(step2_prompt_template.replace('{placeholder}', ''))
    remaining = budget_for_step2 - fixed_tokens

    for m in important_methods:
        name = m['name']
        desc = m.get('description', '（暂无描述）')
        entry = f"  - {name}: {desc}\n"

        # 如果方法有代码且描述为空，附带代码摘要
        code = m.get('code', '')
        if not desc or desc == '（暂无描述）':
            # 只取代码前5行作为补充
            code_lines = code.split('\n')[:5]
            entry += f"    代码片段: {'; '.join(l.strip() for l in code_lines[:3])}\n"

        entry_tokens = estimate_tokens(entry)
        if used_tokens + entry_tokens <= remaining:
            included_methods.append(m)
            used_tokens += entry_tokens
        else:
            break

    methods_text = _build_methods_summary(included_methods)
    step2_prompt = CLASS_PROMPT.format(
        file=group['file'],
        class_name=class_name,
        inherits=group['inherits'],
        class_docstring=group['class_docstring'] or '（无文档）',
        fields=fields_text,
        methods_summary=methods_text,
    )

    return await _single_step_class(client, step2_prompt, class_name, group, model, max_tokens)


async def summarize_all_classes(chunks, config, cache_path=None):
    """为所有类生成概述。
    支持中继：缓存文件中已有的类会跳过，每处理完一个类保存进度。
    """
    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 8000)
    concurrency = config['llm'].get('concurrency', 2)

    # 获取模型输入长度限制
    input_limit = await get_model_input_limit(client, model, config_fallback)

    # 按类分组
    class_chunks = _group_chunks_by_class(chunks)
    print(f"发现 {len(class_chunks)} 个类")

    # 加载已有缓存，跳过已完成的类
    existing_summaries = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            for s in cached:
                cn = s.get('class_name', '')
                if cn and s.get('description'):
                    existing_summaries[cn] = s
            print(f"  中继: 跳过 {len(existing_summaries)} 个已有类概述")
        except Exception:
            pass

    # 过滤出需要处理的类
    need_process = {name: group for name, group in class_chunks.items()
                    if name not in existing_summaries}

    if not need_process:
        await client.close()
        return list(existing_summaries.values())

    # 并发生成概述
    semaphore = asyncio.Semaphore(concurrency)
    done_count = len(existing_summaries)
    total = len(class_chunks)
    done_lock = asyncio.Lock()

    def _save_checkpoint():
        if cache_path:
            all_summaries = list(existing_summaries.values()) + new_summaries
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(all_summaries, f, ensure_ascii=False, indent=2)

    new_summaries = []

    async def process_one(class_name, group):
        nonlocal done_count
        async with semaphore:
            summary = await summarize_class(
                client, class_name, group, model, max_tokens, input_limit,
            )

            async with done_lock:
                done_count += 1
                new_summaries.append(summary)
                print(f"  [{done_count}/{total}] {class_name}: {summary['description'][:50]}")
                # 每完成一个就保存（类数量通常不多）
                _save_checkpoint()

            return summary

    tasks = [process_one(name, group) for name, group in need_process.items()]
    await asyncio.gather(*tasks)

    await client.close()
    return list(existing_summaries.values()) + new_summaries


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
