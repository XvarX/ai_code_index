"""测试 LLM 工具链：校验、截断、两步发送。
用极小的 max_input_tokens 强制触发所有超限分支。
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'utils'))

from config_helper import load_config
from llm_utils import estimate_tokens, parse_llm_json, validate_response, truncate_code


def test_llm_utils():
    """测试 llm_utils 各函数"""
    print("=" * 50)
    print("测试 llm_utils")

    # 1. estimate_tokens
    text_cn = "这是一个测试" * 100
    text_en = "hello world " * 100
    text_mix = text_cn + text_en
    print(f"  estimate_tokens 中文({len(text_cn)}字): {estimate_tokens(text_cn)}")
    print(f"  estimate_tokens 英文({len(text_en)}字): {estimate_tokens(text_en)}")
    print(f"  estimate_tokens 混合({len(text_mix)}字): {estimate_tokens(text_mix)}")

    # 2. parse_llm_json - 各种格式
    cases = [
        ('标准JSON', '{"description": "测试", "module": "scene"}'),
        ('markdown包裹', '```json\n{"description": "测试", "module": "scene"}\n```'),
        ('无语言标记', '```\n{"description": "测试", "module": "scene"}\n```'),
        ('带前缀文本', '以下是结果:\n{"description": "测试", "module": "scene"}'),
        ('空输入', ''),
        ('非JSON', '这是一段普通文字'),
    ]
    for name, text in cases:
        result = parse_llm_json(text)
        print(f"  parse_llm_json [{name}]: {result}")

    # 3. validate_response - 类型修正
    specs = {
        'description': {'type': str, 'default': ''},
        'patterns': {'type': list, 'default': []},
        'key_methods': {'type': list, 'default': []},
    }
    fix_cases = [
        ('正常', {'description': 'OK', 'patterns': ['a'], 'key_methods': ['b']}),
        ('patterns是字符串', {'description': 'OK', 'patterns': '状态机', 'key_methods': ['b']}),
        ('字段缺失', {'description': 'OK'}),
        ('空dict', {}),
        ('非dict', 'not a dict'),
        ('description为None', {'description': None, 'patterns': None}),
    ]
    for name, data in fix_cases:
        result = validate_response(data, specs)
        print(f"  validate_response [{name}]: {result}")

    # 4. truncate_code
    code = '\n'.join([f'    line_{i} = {i}' for i in range(200)])
    truncated = truncate_code(code, 50)
    print(f"  truncate_code 原始{len(code)}字/{estimate_tokens(code)}tokens -> "
          f"截断后{len(truncated)}字/{estimate_tokens(truncated)}tokens")

    print("  [POK] llm_utils 测试通过\n")


async def test_describer(config):
    """测试 describer：强制截断 + 校验"""
    print("=" * 50)
    print("测试 describer（超限截断）")

    from describer import describe_one
    from openai import AsyncOpenAI
    from llm_utils import get_model_input_limit

    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 200)
    input_limit = await get_model_input_limit(client, model, config_fallback)
    print(f"  input_limit: {input_limit}")

    # 构造一个超长的 chunk
    long_code = '\n'.join([f'    x_{i} = self.process_{i}(data)' for i in range(200)])
    chunk = {
        'type': 'function',
        'name': 'test_long_func',
        'file': 'test.py',
        'code': f'def test_long_func(self, data):\n{long_code}',
        'start_line': 1,
        'module_docstring': '测试模块',
        'docstring': '测试超长函数',
        'class_name': 'TestClass',
        'tags': {'module': 'test', 'action': 'process', 'target': 'data'},
        'struct_def': None,
    }

    content, ok = await describe_one(client, chunk, model, max_tokens, input_limit)
    print(f"  LLM返回: ok={ok}, content长度={len(content or '')}")
    print(f"  内容预览: {(content or '')[:120]}")

    await client.close()
    print("  [POK] describer 测试完成\n")


async def test_class_summarizer(config):
    """测试 class_summarizer：强制两步"""
    print("=" * 50)
    print("测试 class_summarizer（超限→两步）")

    from class_summarizer import summarize_class
    from openai import AsyncOpenAI
    from llm_utils import get_model_input_limit

    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 200)
    input_limit = await get_model_input_limit(client, model, config_fallback)
    print(f"  input_limit: {input_limit}")

    # 构造一个有很多方法的类
    methods = []
    for i in range(15):
        methods.append({
            'type': 'method',
            'name': f'method_{i}',
            'file': 'test.py',
            'code': f'def method_{i}(self, data):\n    return data * {i}',
            'start_line': i * 5 + 1,
            'description': f'方法{i}：处理数据并返回结果{i}',
        })

    group = {
        'overview': {
            'type': 'class_overview',
            'name': 'TestClass (概览)',
            'file': 'test.py',
            'code': 'class TestClass(BaseManager):\n    pass',
            'docstring': '测试类概览',
        },
        'methods': methods,
        'file': 'test.py',
        'inherits': 'BaseManager',
        'class_docstring': '这是一个有很多方法的测试类',
        'fields': ['self.data = []', 'self.count = 0'],
    }

    result = await summarize_class(
        client, 'TestClass', group, model, max_tokens, input_limit,
    )
    print(f"  description: {result.get('description', '')}")
    print(f"  responsibility: {result.get('responsibility', '')}")
    print(f"  key_methods: {result.get('key_methods', [])}")
    print(f"  patterns: {result.get('patterns', [])}")
    print(f"  module: {result.get('module', '')}")

    # 检查关键字段不为空
    assert result.get('description'), "description 不应为空"
    assert isinstance(result.get('patterns', []), list), "patterns 应为列表"
    assert isinstance(result.get('key_methods', []), list), "key_methods 应为列表"

    await client.close()
    print("  [POK] class_summarizer 测试完成\n")


async def test_module_summarizer(config):
    """测试 module_summarizer：强制两步"""
    print("=" * 50)
    print("测试 module_summarizer（超限→两步）")

    from module_summarizer import summarize_module
    from openai import AsyncOpenAI
    from llm_utils import get_model_input_limit

    client = AsyncOpenAI(
        api_key=config['llm'].get('api_key') or os.getenv('OPENAI_API_KEY'),
        base_url=config['llm'].get('base_url'),
    )
    model = config['llm']['model']
    max_tokens = config['llm']['max_tokens']
    config_fallback = config['llm'].get('max_input_tokens', 200)
    input_limit = await get_model_input_limit(client, model, config_fallback)
    print(f"  input_limit: {input_limit}")

    # 构造一个有很多函数的模块
    chunks = []
    for i in range(20):
        chunks.append({
            'type': 'method',
            'name': f'process_{i}',
            'file': f'testmod/handler_{i % 3}.py',
            'start_line': i * 10 + 1,
            'code': f'def process_{i}(self, data):\n    return data',
            'description': f'处理函数{i}：负责数据处理的第{i}步',
            'class_name': f'Handler{i % 3}' if i % 3 != 0 else None,
        })

    group = {
        'files': {f'testmod/handler_{i}.py' for i in range(3)},
        'classes': {f'Handler{i}' for i in range(3)},
        'functions': [
            {
                'name': c['name'],
                'file': c['file'],
                'line': c['start_line'],
                'description': c.get('description', ''),
                'class': c.get('class_name') or '',
            }
            for c in chunks
        ],
        'chunks': chunks,
    }

    call_graph = {
        'testmod/handler_0.py:1': ['testmod/handler_1.py:11 (process_1)'],
    }

    result = await summarize_module(
        client, 'testmod', group, call_graph,
        '/test', model, max_tokens, input_limit,
    )
    print(f"  description: {result.get('description', '')}")
    print(f"  responsibility: {result.get('responsibility', '')}")
    print(f"  standard_flow: {result.get('standard_flow', [])}")
    print(f"  entry_points: {result.get('entry_points', [])}")
    print(f"  key_classes: {result.get('key_classes', [])}")
    print(f"  patterns: {result.get('patterns', [])}")

    assert result.get('description'), "description 不应为空"
    assert isinstance(result.get('standard_flow', []), list), "standard_flow 应为列表"
    assert isinstance(result.get('patterns', []), list), "patterns 应为列表"

    await client.close()
    print("  [POK] module_summarizer 测试完成\n")


async def main():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    config = load_config(config_path)

    print(f"config: max_input_tokens={config['llm'].get('max_input_tokens')}")
    print(f"config: model={config['llm']['model']}")
    print()

    # 1. 纯本地测试
    test_llm_utils()

    # 2. LLM 集成测试
    await test_describer(config)
    await test_class_summarizer(config)
    await test_module_summarizer(config)

    print("=" * 50)
    print("全部测试完成")


if __name__ == '__main__':
    asyncio.run(main())
