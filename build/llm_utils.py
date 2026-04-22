"""
llm_utils.py - LLM 调用共享工具
token 估算、JSON 解析、响应校验、代码截断
"""

import json
import logging

logger = logging.getLogger(__name__)


def estimate_tokens(text):
    """粗略估算 token 数。
    CJK 字符约 1 token/字符，ASCII 约 3.5 字符/token。
    对中文+代码混合内容足够准确做截断判断。
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ascii_chars = len(text) - cjk
    return int(cjk + ascii_chars / 3.5)


async def get_model_input_limit(client, model, config_fallback=8000):
    """获取模型最大输入 token 数。
    尝试调 API 获取，失败则用配置值兜底。
    """
    try:
        model_info = await client.models.retrieve(model)
        # 不同 API 返回的属性名不同
        for attr in ('context_window', 'context_length',
                     'max_context_tokens', 'max_input_tokens'):
            val = getattr(model_info, attr, None)
            if val and isinstance(val, int):
                logger.info(f"从 API 获取模型上下文长度: {val}")
                return val
    except Exception:
        pass

    logger.info(f"API 查询失败，使用配置值: {config_fallback}")
    return config_fallback


def parse_llm_json(text):
    """统一 JSON 解析：剥离 markdown 代码块，容错解析。
    成功返回 dict，失败返回 None。
    """
    if not text:
        return None

    text = text.strip()

    # 剥离 markdown 代码块（```json ... ``` 或 ``` ... ```）
    if text.startswith('```'):
        lines = text.split('\n')
        # 跳过第一行（``` 或 ```json）
        text = '\n'.join(lines[1:])
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 对象（找第一个 { 到最后一个 }）
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def validate_response(data, field_specs):
    """校验并修正 LLM 返回的 JSON 结构。

    field_specs 格式:
        {
            "field_name": {"type": str, "default": ""},
            "field_name": {"type": list, "default": []},
        }

    常见修正:
    - list 字段收到字符串 → 包装为 [字符串]
    - str 字段收到 None → 用默认值
    - 字段缺失 → 用默认值
    """
    if not isinstance(data, dict):
        return None

    fixed = {}
    for field, spec in field_specs.items():
        value = data.get(field)
        expected_type = spec['type']
        default = spec.get('default')

        if value is None:
            fixed[field] = default
            continue

        if expected_type == list:
            if isinstance(value, list):
                fixed[field] = value
            elif isinstance(value, str):
                # "状态机" → ["状态机"]
                fixed[field] = [value] if value.strip() else default or []
            else:
                fixed[field] = default or []
        elif expected_type == str:
            if isinstance(value, str):
                fixed[field] = value
            elif isinstance(value, (list, dict)):
                fixed[field] = json.dumps(value, ensure_ascii=False)
            else:
                fixed[field] = str(value) if value else (default or '')
        else:
            fixed[field] = value

    return fixed


def truncate_code(code, max_tokens, marker="    # ... (已截断)"):
    """按行截断代码到指定 token 预算内。
    保留开头行，超出部分用 marker 替代。
    """
    if not code:
        return code

    lines = code.split('\n')
    current = code
    while estimate_tokens(current) > max_tokens and len(lines) > 1:
        lines = lines[:-1]
        current = '\n'.join(lines) + '\n' + marker

    return current
