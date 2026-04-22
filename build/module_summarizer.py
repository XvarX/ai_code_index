"""
module_summarizer.py - 模块概述生成器
分析文件夹级别的代码，提取调用关系和标准流程
"""

import asyncio
import ast
import json
import os
from collections import defaultdict
from openai import AsyncOpenAI
from llm_utils import (
    parse_llm_json, validate_response, estimate_tokens,
    truncate_code, get_model_input_limit,
)

# 响应字段规范
MODULE_STEP1_FIELDS = {
    'important_classes': {'type': list, 'default': []},
    'important_functions': {'type': list, 'default': []},
}

MODULE_STEP2_FIELDS = {
    'description': {'type': str, 'default': ''},
    'responsibility': {'type': str, 'default': ''},
    'standard_flow': {'type': list, 'default': []},
    'entry_points': {'type': list, 'default': []},
    'key_classes': {'type': list, 'default': []},
    'patterns': {'type': list, 'default': []},
}

MODULE_PROMPT = """\
分析以下Python模块的代码结构，输出JSON格式。

[模块名] {module_name}
[模块路径] {module_path}
[文件数量] {file_count} 个文件
[类数量] {class_count} 个类

[文件清单]
{files_list}

[调用关系图]
{call_graph}

[导出的公共接口]
{public_api}

[模块全局变量/常量/字典]
{globals}

请分析这个模块的功能，输出JSON（不要markdown代码块）:
{{
  "description": "一句话描述这个模块的整体功能",
  "responsibility": "这个模块负责什么",
  "standard_flow": [
    "步骤1: ...",
    "步骤2: ...",
    "步骤3: ..."
  ],
  "entry_points": ["外部调用的入口函数/方法列表"],
  "key_classes": ["核心类列表"],
  "patterns": ["设计模式或架构模式，如: 工厂模式/单例/管理器模式"]
}}

注意：
1. standard_flow 要基于真实的调用关系，描述"如何使用这个模块完成一件事"
2. entry_points 是外部最常调用的接口
3. 如果调用关系不明显，可以基于文件名和类名推断
"""

MODULE_STEP1_PROMPT = """\
分析以下Python模块的结构，判断哪些类和函数最能代表这个模块的功能。

[模块名] {module_name}
[模块路径] {module_path}
[文件数量] {file_count} 个文件

[类及方法列表]
{classes_and_methods}

请输出JSON（不要markdown代码块）:
{{
  "important_classes": ["类名1", ...],
  "important_functions": ["函数名1", ...]
}}

选择标准:
1. 模块对外暴露的核心接口
2. 体现模块主要功能的类和方法
3. 被其他模块调用的入口函数
4. 重要类选2-4个，重要函数选3-5个"""


def _group_chunks_by_module(chunks, config):
    """按模块（文件夹）分组，智能识别子模块"""
    modules = defaultdict(lambda: {
        'files': set(),
        'classes': set(),
        'functions': [],
        'globals': [],
        'chunks': [],
    })

    module_config = config.get('project', {}).get('module_analysis', {})
    force_whole = set(module_config.get('force_whole_modules', []))
    skip_subs = set(module_config.get('skip_submodules', []))
    min_files = module_config.get('min_files_for_submodule', 2)
    project_root = config.get('project', {}).get('root', '')

    dir_structure = defaultdict(set)
    for chunk in chunks:
        filepath = chunk['file']
        if project_root and filepath.startswith(project_root):
            rel_path = filepath[len(project_root):].lstrip('/\\')
        else:
            rel_path = filepath

        parts = rel_path.replace('\\', '/').split('/')
        if len(parts) >= 1:
            for i in range(1, len(parts)):
                dir_path = '/'.join(parts[:i])
                dir_structure[dir_path].add(filepath)

    def _find_module(parts):
        if len(parts) < 1:
            return 'root'
        top_dir = parts[0]
        if top_dir in force_whole:
            return top_dir
        if len(parts) <= 1:
            return top_dir
        module = top_dir
        max_depth = len(parts) - 1
        for depth in range(2, max_depth + 1):
            sub_dir_name = parts[depth - 1]
            if sub_dir_name in skip_subs:
                break
            candidate = '/'.join(parts[:depth])
            if len(dir_structure.get(candidate, set())) >= min_files:
                module = candidate
            else:
                break
        return module

    for chunk in chunks:
        filepath = chunk['file']
        if project_root and filepath.startswith(project_root):
            rel_path = filepath[len(project_root):].lstrip('/\\')
        else:
            rel_path = filepath

        parts = rel_path.replace('\\', '/').split('/')
        module = _find_module(parts)

        modules[module]['files'].add(filepath)
        modules[module]['chunks'].append(chunk)

        if chunk.get('class_name'):
            modules[module]['classes'].add(chunk['class_name'])

        if chunk['type'] in ('function', 'method'):
            modules[module]['functions'].append({
                'name': chunk['name'],
                'file': filepath,
                'line': chunk['start_line'],
                'description': chunk.get('description', ''),
                'class': chunk.get('class_name') or '',
            })

        if chunk['type'] == 'global':
            modules[module]['globals'].append({
                'name': chunk['name'],
                'file': filepath,
                'line': chunk['start_line'],
                'description': chunk.get('description', ''),
                'code': chunk.get('code', ''),
            })

    return modules


def _build_simple_call_graph(module_name, chunks):
    """基于 AST 分析调用关系（解析函数调用节点）"""
    import os.path

    symbol_table = defaultdict(list)
    for chunk in chunks:
        filepath = chunk['file']
        func_name = chunk.get('name', '')
        if chunk['type'] in ('function', 'method') and func_name:
            symbol_table[func_name].append((filepath, chunk['start_line']))

    call_graph = defaultdict(set)

    for chunk in chunks:
        filepath = chunk['file']
        code = chunk.get('code', '')
        if chunk['type'] not in ('function', 'method'):
            continue

        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue

        caller_key = f"{filepath}:{chunk['start_line']}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called_name = None
                if isinstance(node.func, ast.Name):
                    called_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    called_name = node.func.attr

                if called_name and called_name in symbol_table:
                    for callee_file, callee_line in symbol_table[called_name]:
                        callee_key = f"{callee_file}:{callee_line} ({called_name})"
                        call_graph[caller_key].add(callee_key)

    return {k: list(v) for k, v in call_graph.items()}


def _format_module_info(module_name, group, call_graph):
    """格式化模块信息用于 prompt"""
    files_list = sorted(group['files'])
    classes_list = sorted(group['classes'])

    files_text = '\n'.join(f"  - {f}" for f in files_list[:10])
    if len(files_list) > 10:
        files_text += f"\n  ... 还有 {len(files_list) - 10} 个文件"

    call_text = ""
    if call_graph:
        for caller, callees in list(call_graph.items())[:10]:
            call_text += f"  {caller} 调用:\n"
            for callee in list(callees)[:3]:
                call_text += f"    -> {callee}\n"
        if not call_text:
            call_text = "  （未分析到明确的调用关系，基于文件名推断）"
    else:
        call_text = "  （调用关系分析失败）"

    functions_with_desc = [f for f in group['functions'] if f['description']]
    public_api = []
    for func in functions_with_desc[:15]:
        if func['class']:
            public_api.append(f"  - {func['class']}.{func['name']}: {func['description']}")
        else:
            public_api.append(f"  - {func['name']}: {func['description']}")

    # 全局变量（字典、常量等）直接展示代码
    globals_text = ""
    for g in group.get('globals', []):
        desc = g.get('description', '')
        code = g.get('code', '')
        globals_text += f"  # {g['name']}"
        if desc:
            globals_text += f" — {desc}"
        globals_text += "\n"
        # 缩进代码
        for line in code.split('\n')[:20]:
            globals_text += f"    {line}\n"
    if not globals_text:
        globals_text = "  （无全局变量）"

    api_text = '\n'.join(public_api) if public_api else "  （未找到公共接口）"

    return {
        'files_list': files_text,
        'file_count': len(files_list),
        'class_count': len(classes_list),
        'call_graph': call_text,
        'public_api': api_text,
        'globals': globals_text,
        'key_classes': ', '.join(list(classes_list)[:5]),
    }


def _build_classes_and_methods_text(group):
    """构建模块内类和方法列表（仅名称，用于 Step1 筛选）"""
    lines = []

    # 按类分组
    class_methods = defaultdict(list)
    standalone_funcs = []
    for func in group['functions']:
        if func['class']:
            class_methods[func['class']].append(func['name'])
        else:
            standalone_funcs.append(func['name'])

    for cls_name in sorted(group['classes']):
        methods = class_methods.get(cls_name, [])
        if methods:
            lines.append(f"  {cls_name}: {', '.join(methods[:10])}")
        else:
            lines.append(f"  {cls_name}")

    for func_name in standalone_funcs[:10]:
        lines.append(f"  (函数) {func_name}")

    return '\n'.join(lines) if lines else '  （空模块）'


def _make_module_summary(module_name, info, result):
    """从校验后的结果构建模块摘要"""
    return {
        'type': 'module_summary',
        'name': f"{module_name} (模块概述)",
        'module_name': module_name,
        'file': f"{module_name}/",
        'description': result.get('description', ''),
        'responsibility': result.get('responsibility', ''),
        'standard_flow': result.get('standard_flow', []),
        'entry_points': result.get('entry_points', []),
        'key_classes': result.get('key_classes', []),
        'patterns': result.get('patterns', []),
        'file_count': info['file_count'],
        'class_count': info['class_count'],
        'text_for_embedding': f"{module_name}模块: {result.get('description', '')}。{result.get('responsibility', '')}",
    }


def _make_fallback_summary(module_name, info, group):
    """生成兜底的模块摘要"""
    return {
        'type': 'module_summary',
        'name': f"{module_name} (模块概述)",
        'module_name': module_name,
        'file': f"{module_name}/",
        'description': f'{module_name} 模块，包含 {info["file_count"]} 个文件，{info["class_count"]} 个类',
        'responsibility': '',
        'standard_flow': [],
        'entry_points': [],
        'key_classes': list(group['classes'])[:5],
        'patterns': [],
        'file_count': info['file_count'],
        'class_count': info['class_count'],
        'text_for_embedding': f"{module_name}模块",
    }


async def summarize_module(client, module_name, group, call_graph,
                            project_root, model, max_tokens, input_limit):
    """为单个模块生成概述。
    内容在限制内 → 单步发送全部。
    内容超长 → 两步：先筛重要项，再用重要内容生成摘要。
    """
    info = _format_module_info(module_name, group, call_graph)

    prompt = MODULE_PROMPT.format(
        module_name=module_name,
        module_path=f"{project_root}/{module_name}",
        file_count=info['file_count'],
        class_count=info['class_count'],
        files_list=info['files_list'],
        call_graph=info['call_graph'],
        public_api=info['public_api'],
        globals=info['globals'],
    )

    budget = input_limit - max_tokens - 300
    prompt_tokens = estimate_tokens(prompt)

    if prompt_tokens <= budget:
        # 单步：内容在限制内
        return await _single_step_module(
            client, prompt, module_name, info, group, model, max_tokens,
        )

    # 两步：先筛重要项
    return await _two_step_module(
        client, module_name, group, info, call_graph, project_root,
        model, max_tokens, input_limit,
    )


async def _single_step_module(client, prompt, module_name, info, group,
                               model, max_tokens):
    """单步生成模块概述"""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens + 500,
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()

        result = parse_llm_json(content)
        if result:
            validated = validate_response(result, MODULE_STEP2_FIELDS)
            if validated and validated.get('description'):
                return _make_module_summary(module_name, info, validated)

    except Exception as e:
        print(f"  ❌ 模块 {module_name} 概述生成失败: {e}")

    return _make_fallback_summary(module_name, info, group)


async def _two_step_module(client, module_name, group, info, call_graph,
                            project_root, model, max_tokens, input_limit):
    """两步生成模块概述：先筛重要项，再用重要内容生成摘要"""

    # ---- Step 1: 筛选重要类和函数 ----
    classes_methods_text = _build_classes_and_methods_text(group)

    step1_prompt = MODULE_STEP1_PROMPT.format(
        module_name=module_name,
        module_path=f"{project_root}/{module_name}",
        file_count=info['file_count'],
        classes_and_methods=classes_methods_text,
    )

    important_classes = []
    important_functions = []
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
            validated = validate_response(result, MODULE_STEP1_FIELDS)
            if validated:
                important_classes = validated['important_classes']
                important_functions = validated['important_functions']
    except Exception as e:
        print(f"  ⚠️ 模块 {module_name} Step1 筛选失败: {e}")

    # ---- Step 2: 用重要内容生成摘要 ----
    budget_for_step2 = input_limit - max_tokens - 500

    # 过滤公共接口：只保留重要的类和函数
    filtered_api = []
    for func in group['functions']:
        if func['description']:
            is_important = False
            if func['class'] and func['class'] in important_classes:
                is_important = True
            elif func['name'] in important_functions:
                is_important = True
            # 如果没有筛选结果，取前15个
            elif not important_classes and not important_functions:
                is_important = True

            if is_important:
                if func['class']:
                    filtered_api.append(f"  - {func['class']}.{func['name']}: {func['description']}")
                else:
                    filtered_api.append(f"  - {func['name']}: {func['description']}")

    # 按预算截断公共接口
    api_text = '\n'.join(filtered_api)
    if estimate_tokens(api_text) > budget_for_step2 - 500:
        # 逐条添加直到预算用完
        kept = []
        used = 0
        for line in filtered_api:
            t = estimate_tokens(line)
            if used + t <= budget_for_step2 - 500:
                kept.append(line)
                used += t
            else:
                break
        api_text = '\n'.join(kept)

    if not api_text:
        api_text = "  （未找到公共接口）"

    # 构建精简的调用关系
    call_text = ""
    if call_graph:
        for caller, callees in list(call_graph.items())[:5]:
            call_text += f"  {caller} 调用:\n"
            for callee in list(callees)[:2]:
                call_text += f"    -> {callee}\n"

    step2_prompt = MODULE_PROMPT.format(
        module_name=module_name,
        module_path=f"{project_root}/{module_name}",
        file_count=info['file_count'],
        class_count=info['class_count'],
        files_list=info['files_list'],
        call_graph=call_text or "  （调用关系分析失败）",
        public_api=api_text,
        globals=info['globals'],
    )

    return await _single_step_module(
        client, step2_prompt, module_name, info, group, model, max_tokens,
    )


async def summarize_all_modules(chunks, config):
    """为所有模块生成概述"""
    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 8000)
    project_root = config['project']['root']
    concurrency = config['llm'].get('concurrency', 2)

    # 获取模型输入长度限制
    input_limit = await get_model_input_limit(client, model, config_fallback)

    # 按模块分组
    modules = _group_chunks_by_module(chunks, config)
    print(f"发现 {len(modules)} 个模块")

    for module_name in sorted(modules.keys()):
        group = modules[module_name]
        print(f"  - {module_name}: {len(group['files'])} 个文件, {len(group['classes'])} 个类")

    # 并发生成概述
    semaphore = asyncio.Semaphore(concurrency)
    done_count = 0
    done_lock = asyncio.Lock()

    async def process_one(module_name, group):
        nonlocal done_count
        async with semaphore:
            call_graph = _build_simple_call_graph(module_name, group['chunks'])

            summary = await summarize_module(
                client, module_name, group, call_graph,
                project_root, model, max_tokens, input_limit,
            )

            async with done_lock:
                done_count += 1
                print(f"  [{done_count}/{len(modules)}] {module_name}: {summary['description'][:50]}")

            return summary

    try:
        tasks = [process_one(name, group) for name, group in modules.items()]
        module_summaries = await asyncio.gather(*tasks)
    finally:
        await client.close()

    return [s for s in module_summaries if s]


if __name__ == '__main__':
    import yaml
    with open('../config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open('../data/described_chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    module_summaries = asyncio.run(summarize_all_modules(chunks, config))

    with open('../data/module_summaries.json', 'w', encoding='utf-8') as f:
        json.dump(module_summaries, f, ensure_ascii=False, indent=2)

    print(f"\n模块概述生成完成: {len(module_summaries)} 个模块")
