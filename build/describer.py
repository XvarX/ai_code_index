"""
describer.py - LLM描述生成器
用LLM为每个代码块生成功能描述 + 自动打标签
"""

import asyncio
import json
import os
from openai import AsyncOpenAI
from llm_utils import parse_llm_json, validate_response, estimate_tokens, truncate_code, get_model_input_limit

PROMPT_TEMPLATE = """\
分析以下Python代码，输出JSON格式，不要输出其他内容。

[文件] {file}
[类] {class_name}
[模块说明] {module_doc}
{class_context}
{extra_context}

[代码]
{code}

请输出以下JSON（不要markdown代码块，直接输出JSON）:
{{
  "description": "一句中文描述功能",
  "module": "所属模块，如 scene/activity/reward/player/npc/battle/config",
  "action": "动作类型: create/delete/update/query/save/handle/check/init/start/stop/send/calc/other",
  "target": "操作对象，如 scene/npc/player/item/reward/config/activity/dungeon/boss",
  "pattern": "代码模式: 创建流程/事件处理/定时任务/协议处理/数据持久化/状态机/奖励发放/匹配组队，没有则为空"
}}"""


def _parse_llm_response(text, chunk, fallback_tags):
    """解析LLM返回的JSON，失败则用自动标签兜底"""
    # 字段规范
    field_specs = {
        'description': {'type': str, 'default': ''},
        'module': {'type': str, 'default': ''},
        'action': {'type': str, 'default': ''},
        'target': {'type': str, 'default': ''},
        'pattern': {'type': str, 'default': ''},
    }

    result = parse_llm_json(text)
    if result and result.get('description'):
        validated = validate_response(result, field_specs)
        if validated:
            validated['module'] = validated['module'] or fallback_tags.get('module', '')
            validated['action'] = validated['action'] or fallback_tags.get('action', 'other')
            validated['target'] = validated['target'] or fallback_tags.get('target', '')
            return validated

    # JSON 解析失败或 description 为空，用原始文本兜底
    raw = text.strip() if text else ''
    # 如果 raw 看起来像 JSON，取 description 字段
    if raw.startswith('{'):
        parsed = parse_llm_json(raw)
        if parsed and parsed.get('description'):
            desc = parsed['description']
        else:
            desc = raw[:100]
    else:
        desc = raw[:100]

    return {
        'description': desc,
        'module': fallback_tags.get('module', ''),
        'action': fallback_tags.get('action', 'other'),
        'target': fallback_tags.get('target', ''),
        'pattern': '',
    }


async def describe_one(client, chunk, model, max_tokens, input_limit):
    extra = ''
    if chunk.get('docstring'):
        extra += f"[函数文档] {chunk['docstring']}\n"
    if chunk.get('tags'):
        tags = chunk['tags']
        extra += f"[自动猜测] 模块:{tags['module']} 动作:{tags['action']} 对象:{tags['target']}\n"

    # 添加类上下文（类定义、字段、其他方法签名）
    class_context = ''
    if chunk.get('struct_def'):
        class_context = f"[所属类定义]\n{chunk['struct_def']}\n"

    code = chunk['code']

    # 构建 prompt 并检查 token 长度
    prompt = PROMPT_TEMPLATE.format(
        file=chunk['file'],
        class_name=chunk.get('class_name') or ('全局代码' if chunk.get('type') == 'global' else '无（顶层函数）'),
        module_doc=(chunk.get('module_docstring') or '无')[:200],
        class_context=class_context,
        extra_context=extra,
        code=code,
    )

    prompt_tokens = estimate_tokens(prompt)
    budget = input_limit - max_tokens - 200  # 预留输出和余量
    if prompt_tokens > budget and budget > 0:
        # 需要截断 code 部分：估算非 code 部分的 token，剩余给 code
        non_code = PROMPT_TEMPLATE.format(
            file=chunk['file'],
            class_name=chunk.get('class_name') or ('全局代码' if chunk.get('type') == 'global' else '无（顶层函数）'),
            module_doc=(chunk.get('module_docstring') or '无')[:200],
            class_context=class_context,
            extra_context=extra,
            code='',
        )
        code_budget = budget - estimate_tokens(non_code)
        if code_budget > 100:
            code = truncate_code(code, code_budget)
            prompt = PROMPT_TEMPLATE.format(
                file=chunk['file'],
                class_name=chunk.get('class_name') or ('全局代码' if chunk.get('type') == 'global' else '无（顶层函数）'),
                module_doc=(chunk.get('module_docstring') or '无')[:200],
                class_context=class_context,
                extra_context=extra,
                code=code,
            )

    resp = await client.chat.completions.create(
        model=model,
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=max_tokens + 200,  # JSON比纯描述长一点
        temperature=0.1,
    )
    content = resp.choices[0].message.content.strip()
    return content, True


async def describe_all(chunks, config):
    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 8000)
    concurrency = config['llm'].get('concurrency', 5)
    semaphore = asyncio.Semaphore(concurrency)

    # 获取模型输入长度限制
    input_limit = await get_model_input_limit(client, model, config_fallback)
    total = len(chunks)
    done_count = 0
    done_lock = asyncio.Lock()

    async def process_one(chunk):
        nonlocal done_count
        async with semaphore:
            fallback_tags = chunk.get('tags', {})
            try:
                content, ok = await describe_one(client, chunk, model, max_tokens, input_limit)
            except Exception as e:
                content = ''
                ok = False
                print(f"  LLM调用失败 {chunk['name']}: {e}")

            # 解析结果
            parsed = _parse_llm_response(content, chunk, fallback_tags)

            # 如果描述为空，用原始返回兜底
            if not parsed['description'] and content:
                parsed['description'] = content[:80]
            chunk['description'] = parsed['description']

            # 用 LLM 的标签覆盖自动标签
            tags = chunk.get('tags', {})
            tags['module'] = parsed['module']
            tags['action'] = parsed['action']
            tags['target'] = parsed['target']
            if parsed['pattern']:
                tags['patterns'] = [parsed['pattern']]
            chunk['tags'] = tags

            async with done_lock:
                done_count += 1
                print(f"  [{done_count}/{total}] {chunk['name']}: {parsed['description'][:60]}")

            return chunk, ok

    tasks = [process_one(c) for c in chunks]
    results = await asyncio.gather(*tasks)

    success = sum(1 for _, ok in results if ok)
    fail = sum(1 for _, ok in results if not ok)
    print(f"描述生成完成: 成功 {success}, 失败 {fail}")

    await client.close()
    return [chunk for chunk, _ in results]


if __name__ == '__main__':
    import yaml
    with open('../config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open('../data/tagged_chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    chunks = asyncio.run(describe_all(chunks, config))
    with open('../data/described_chunks.json', 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print("描述生成完毕")
