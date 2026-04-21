"""
module_summarizer.py - 模块概述生成器
分析文件夹级别的代码，提取调用关系和标准流程
"""

import asyncio
import json
import os
import sys
from collections import defaultdict
from openai import AsyncOpenAI

# 添加 mcp_server 到路径以导入 SCIPIndex
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_server'))
from scip_index import SCIPIndex

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


def _group_chunks_by_module(chunks, config):
    """按模块（文件夹）分组，智能识别子模块"""
    modules = defaultdict(lambda: {
        'files': set(),
        'classes': set(),
        'functions': [],
        'chunks': [],
    })

    # 获取配置
    module_config = config.get('project', {}).get('module_analysis', {})
    force_whole = set(module_config.get('force_whole_modules', []))
    skip_subs = set(module_config.get('skip_submodules', []))
    min_files = module_config.get('min_files_for_submodule', 2)

    # 获取项目根目录，用于规范化路径
    project_root = config.get('project', {}).get('root', '')

    # 统计每个目录下的文件数（递归），用于智能检测子模块
    dir_structure = defaultdict(set)  # dir -> set of files (含子目录文件)
    for chunk in chunks:
        filepath = chunk['file']
        # 规范化路径：去掉绝对路径前缀，统一用 / 分隔
        if project_root and filepath.startswith(project_root):
            rel_path = filepath[len(project_root):].lstrip('/\\')
        else:
            rel_path = filepath

        parts = rel_path.replace('\\', '/').split('/')
        if len(parts) >= 1:
            # 只记录目录层级（不包括文件名本身）
            for i in range(1, len(parts)):
                dir_path = '/'.join(parts[:i])
                dir_structure[dir_path].add(filepath)

    def _find_module(parts):
        """从顶层向下递归查找最深的合格子模块"""
        if len(parts) < 1:
            return 'root'

        top_dir = parts[0]

        # 强制整体模块
        if top_dir in force_whole:
            return top_dir

        # 文件直接在顶层目录下，没有子目录
        if len(parts) <= 1:
            return top_dir

        module = top_dir
        max_depth = len(parts) - 1  # 目录深度（不含文件名）

        # 从第 2 层开始，逐层向下检测
        for depth in range(2, max_depth + 1):
            sub_dir_name = parts[depth - 1]

            # 该子目录在跳过列表中，停止深入
            if sub_dir_name in skip_subs:
                break

            candidate = '/'.join(parts[:depth])

            # 该目录有足够的文件，更新为更深的模块
            if len(dir_structure.get(candidate, set())) >= min_files:
                module = candidate
            else:
                # 文件不够，不继续深入
                break

        return module

    for chunk in chunks:
        filepath = chunk['file']

        # 规范化路径
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

    return modules


def _build_simple_call_graph(module_name, chunks):
    """基于文件名和import分析调用关系（无需LSP的简单版本）"""
    # 分析 import 关系
    imports = defaultdict(set)

    for chunk in chunks:
        filepath = chunk['file']
        code = chunk.get('code', '')

        # 简单的 import 分析（识别 from xxx import yyy）
        for line in code.split('\n'):
            line = line.strip()
            if line.startswith('from ') and ' import ' in line:
                # from .xxx import yyy 或 from gameplay.xxx import yyy
                parts = line.split()
                if len(parts) >= 4:
                    import_path = parts[1]
                    # 检查是否是同一模块内的导入
                    if module_name in import_path or import_path.startswith('.'):
                        imported = parts[3]
                        imports[filepath].add(imported)

    return dict(imports)


async def _build_scip_call_graph(module_name, chunks, scip_index):
    """使用 SCIP 索引分析函数调用关系"""
    call_graph = defaultdict(list)

    # 找到模块路径前缀
    module_prefix = ""
    for chunk in chunks:
        if chunk['file']:
            parts = chunk['file'].replace('\\', '/').split('/')
            for i in range(len(parts)):
                prefix = '/'.join(parts[:i+1])
                if prefix == module_name.replace('\\', '/'):
                    module_prefix = chunk['file'].rsplit(module_name.replace('\\', '/'), 1)[0]
                    break
            if module_prefix:
                break

    # 从 SCIP 索引获取调用关系
    graph = scip_index.get_module_call_graph(module_name)

    # 转换为原有格式（set -> list）
    for key, callees in graph.items():
        call_graph[key] = list(callees)

    return dict(call_graph)


def _format_module_info(module_name, group, call_graph):
    """格式化模块信息用于 prompt"""
    files_list = sorted(group['files'])
    classes_list = sorted(group['classes'])

    # 格式化文件列表
    files_text = '\n'.join(f"  - {f}" for f in files_list[:10])
    if len(files_list) > 10:
        files_text += f"\n  ... 还有 {len(files_list) - 10} 个文件"

    # 格式化调用关系
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

    # 提取公共接口（有描述的方法）
    functions_with_desc = [f for f in group['functions'] if f['description']]
    public_api = []
    for func in functions_with_desc[:15]:
        if func['class']:
            public_api.append(f"  - {func['class']}.{func['name']}: {func['description']}")
        else:
            public_api.append(f"  - {func['name']}: {func['description']}")

    api_text = '\n'.join(public_api) if public_api else "  （未找到公共接口）"

    return {
        'files_list': files_text,
        'file_count': len(files_list),
        'class_count': len(classes_list),
        'call_graph': call_text,
        'public_api': api_text,
        'key_classes': ', '.join(list(classes_list)[:5]),
    }


async def summarize_module(client, module_name, group, call_graph, project_root, model, max_tokens):
    """为单个模块生成概述"""
    info = _format_module_info(module_name, group, call_graph)

    prompt = MODULE_PROMPT.format(
        module_name=module_name,
        module_path=f"{project_root}/{module_name}",
        file_count=info['file_count'],
        class_count=info['class_count'],
        files_list=info['files_list'],
        call_graph=info['call_graph'],
        public_api=info['public_api'],
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=max_tokens + 500,
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
            # 用于向量化
            'text_for_embedding': f"{module_name}模块: {result.get('description', '')}。{result.get('responsibility', '')}",
        }
    except Exception as e:
        print(f"  ❌ 模块 {module_name} 概述生成失败: {e}")
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


async def summarize_all_modules(chunks, config, use_scip=True):
    """为所有模块生成概述"""
    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    project_root = config['project']['root']
    concurrency = config['llm'].get('concurrency', 2)

    # 按模块分组（传入 config 以支持智能检测）
    modules = _group_chunks_by_module(chunks, config)
    print(f"发现 {len(modules)} 个模块")

    # 打印模块列表用于调试
    for module_name in sorted(modules.keys()):
        group = modules[module_name]
        print(f"  - {module_name}: {len(group['files'])} 个文件, {len(group['classes'])} 个类")

    # 加载 SCIP 索引
    shared_scip = None
    if use_scip:
        scip_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'index.scip')
        if os.path.exists(scip_path):
            try:
                shared_scip = SCIPIndex.from_file(scip_path, project_root,
                                                   rag_dirs=config['project'].get('rag_dirs'))
            except Exception as e:
                print(f"  SCIP 索引加载失败，使用简单分析: {e}")
                shared_scip = None
        else:
            print("  SCIP 索引文件不存在，使用简单分析")
            shared_scip = None

    # 并发生成概述
    semaphore = asyncio.Semaphore(concurrency)
    done_count = 0
    done_lock = asyncio.Lock()

    async def process_one(module_name, group):
        nonlocal done_count
        async with semaphore:
            # 分析调用关系（SCIP 索引）
            if shared_scip:
                try:
                    call_graph = await _build_scip_call_graph(module_name, group['chunks'], shared_scip)
                except Exception as e:
                    print(f"  SCIP 分析失败，使用简单分析: {e}")
                    call_graph = _build_simple_call_graph(module_name, group['chunks'])
            else:
                call_graph = _build_simple_call_graph(module_name, group['chunks'])

            summary = await summarize_module(
                client, module_name, group, call_graph,
                project_root, model, max_tokens
            )

            async with done_lock:
                done_count += 1
                print(f"  [{done_count}/{len(modules)}] {module_name}: {summary['description'][:50]}")

            return summary

    try:
        tasks = [process_one(name, group) for name, group in modules.items()]
        module_summaries = await asyncio.gather(*tasks)
    finally:
        # 所有模块分析完成后，关闭 AsyncOpenAI 客户端
        await client.close()

    return [s for s in module_summaries if s]


if __name__ == '__main__':
    import yaml
    with open('../config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    with open('../data/described_chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)

    # 传入 use_scip=False 因为独立运行时 SCIP 可能不可用
    module_summaries = asyncio.run(summarize_all_modules(chunks, config, use_scip=False))

    with open('../data/module_summaries.json', 'w', encoding='utf-8') as f:
        json.dump(module_summaries, f, ensure_ascii=False, indent=2)

    print(f"\n模块概述生成完成: {len(module_summaries)} 个模块")
