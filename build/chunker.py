"""
chunker.py - 代码切块器（ast版本）
将Python代码按函数/类粒度拆分成chunk

切块策略：
- 顶层函数 → 1个chunk（太长则拆分）
- 类 → 概览chunk（定义+字段+方法签名）+ 每个方法各1个chunk
- 长函数/方法（>150行）→ 按语句块拆分
"""

import ast
import os
import json

MAX_CHUNK_LINES = 150


def _read_source(filepath):
    """读取源文件，自动处理编码"""
    with open(filepath, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode('latin-1')


def _get_source_lines(source):
    """按行切分源码"""
    return source.splitlines()


def _extract_node_source(source_lines, node):
    """从行数组中提取 ast 节点对应的源码"""
    # ast 行号从1开始
    start = node.lineno - 1
    end = node.end_lineno  # end_lineno 也是从1开始，切片时刚好
    return '\n'.join(source_lines[start:end])


def _node_line_count(node):
    return node.end_lineno - node.lineno + 1


# ============================================================
# 提取类概览
# ============================================================

def _extract_class_overview(class_node, source_lines):
    """
    提取类概览：类定义 + 装饰器 + docstring + 类字段 + 所有方法签名
    """
    lines = []

    # 装饰器
    for dec in class_node.decorator_list:
        lines.append(_extract_node_source(source_lines, dec))

    # 类定义行: class XXX(Base):
    class_def_line = source_lines[class_node.lineno - 1]
    lines.append(class_def_line)

    for item in class_node.body:
        if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
            # docstring
            lines.append(f'    """{item.value.value.split(chr(10))[0]}"""')
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            # 类字段: x = 10 / name: str = "foo"
            lines.append('    ' + _extract_node_source(source_lines, item))
        elif isinstance(item, ast.FunctionDef) or isinstance(item, ast.AsyncFunctionDef):
            # 方法签名（不包含实现）
            sig = _extract_method_signature(item, source_lines)
            lines.append(sig)
        elif isinstance(item, ast.Pass):
            lines.append('    pass')

    return '\n'.join(lines)


def _extract_method_signature(func_node, source_lines):
    """提取方法签名：def xxx(self, a: int) -> bool: + docstring首行"""
    lines = []

    # 装饰器
    for dec in func_node.decorator_list:
        lines.append('    @' + _extract_node_source(source_lines, dec).lstrip('@'))

    # 从源码取签名（从 def 到 : 结束）
    # ast 不直接给签名文本，我们从源码行中提取
    start = func_node.lineno - 1
    sig_lines = []
    paren_depth = 0
    found_def = False

    for i in range(start, len(source_lines)):
        line = source_lines[i]
        sig_lines.append('    ' + line if not line.startswith('    ') else line)
        paren_depth += line.count('(') - line.count(')')
        found_def = found_def or 'def ' in line

        if found_def and paren_depth <= 0 and ':' in line:
            # 检查是不是真的签名结尾的冒号（排除默认值中的冒号如 type hints）
            # 简单处理：括号闭合了且行尾是冒号
            stripped = line.rstrip()
            if stripped.endswith(':') and paren_depth <= 0:
                break

    sig = '\n'.join(sig_lines)

    # docstring首行
    if func_node.body:
        first = func_node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                first_line = first.value.value.split('\n')[0][:80]
                sig += f'\n        """{first_line}"""'

    return sig


# ============================================================
# 提取函数签名 chunk
# ============================================================

def _extract_signature_source(func_node, source_lines):
    """提取函数签名 + docstring + 前几行逻辑"""
    lines = []

    # 装饰器
    for dec in func_node.decorator_list:
        lines.append(_extract_node_source(source_lines, dec))

    # 签名行
    start = func_node.lineno - 1
    paren_depth = 0
    found_def = False
    sig_end = start

    for i in range(start, len(source_lines)):
        line = source_lines[i]
        paren_depth += line.count('(') - line.count(')')
        found_def = found_def or 'def ' in line
        if found_def and paren_depth <= 0 and line.rstrip().endswith(':'):
            sig_end = i
            break

    for i in range(start, sig_end + 1):
        lines.append(source_lines[i])

    # docstring
    if func_node.body:
        first = func_node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                ds = first.value.value
                lines.append(f'    """{ds.split(chr(10))[0]}"""')

    # body 前几行（跳过 docstring）
    body_start = 0
    if func_node.body:
        first = func_node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                body_start = 1

    count = 0
    for item in func_node.body[body_start:body_start + 3]:
        text = _extract_node_source(source_lines, item)
        for line in text.split('\n'):
            lines.append(line)
        count += text.count('\n') + 1
        if count > 20:
            lines.append('    ... (后续见拆分块)')
            break

    return '\n'.join(lines)


# ============================================================
# 长函数拆分
# ============================================================

def _split_long_function(func_node, source_lines, filepath, module_doc, class_name=None):
    """将过长的函数按语句块拆分"""
    func_name = func_node.name
    line_count = _node_line_count(func_node)

    # 第一个 chunk：签名 + docstring + 前几行
    sig_source = _extract_signature_source(func_node, source_lines)
    chunks = [{
        'type': 'function',
        'name': func_name,
        'code': sig_source,
        'file': filepath,
        'start_line': func_node.lineno,
        'end_line': func_node.end_lineno,
        'module_docstring': module_doc,
        'docstring': ast.get_docstring(func_node) or '',
        'class_name': class_name,
        'struct_def': None,
    }]

    # 找到 body 语句的起始位置（跳过 docstring）
    body_items = list(func_node.body)
    if body_items and isinstance(body_items[0], ast.Expr):
        if isinstance(body_items[0].value, ast.Constant) and isinstance(body_items[0].value.value, str):
            body_items = body_items[1:]

    # 按语句块拆分
    current_lines = []
    current_start = None

    for item in body_items:
        text = _extract_node_source(source_lines, item)
        item_lines = text.split('\n')

        if current_start is None:
            current_start = item.lineno

        if len(current_lines) + len(item_lines) > MAX_CHUNK_LINES and current_lines:
            chunks.append({
                'type': 'function_part',
                'name': f"{func_name} (续)",
                'code': '\n'.join(current_lines),
                'file': filepath,
                'start_line': current_start,
                'end_line': current_start + len(current_lines) - 1,
                'module_docstring': module_doc,
                'docstring': '',
                'class_name': class_name,
                'struct_def': None,
            })
            current_lines = []
            current_start = item.lineno

        current_lines.extend(item_lines)

    if current_lines:
        chunks.append({
            'type': 'function_part',
            'name': f"{func_name} (续)",
            'code': '\n'.join(current_lines),
            'file': filepath,
            'start_line': current_start,
            'end_line': current_start + len(current_lines) - 1,
            'module_docstring': module_doc,
            'docstring': '',
            'class_name': class_name,
            'struct_def': None,
        })

    return chunks


# ============================================================
# 主提取逻辑
# ============================================================

def _is_skip_global_node(node):
    """判断顶层节点是否应该跳过（import、模块docstring）"""
    # 跳过 import 语句
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    # 跳过模块 docstring（已经通过 module_doc 捕获）
    if isinstance(node, ast.Expr):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return True
    return False


def extract_chunks(filepath):
    """从单个Python文件提取所有代码块"""
    source = _read_source(filepath)

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"  语法错误，跳过 {filepath}: {e}")
        return []

    source_lines = _get_source_lines(source)

    # 模块 docstring
    module_doc = ast.get_docstring(tree) or ''

    chunks = []

    # 收集连续的全局语句，遇到函数/类时刷新
    global_nodes = []

    def _flush_global_nodes():
        """将累积的全局语句刷为一个 chunk"""
        if not global_nodes:
            return
        code_parts = []
        for n in global_nodes:
            code_parts.append(_extract_node_source(source_lines, n))
        code = '\n'.join(code_parts)
        first = global_nodes[0]
        last = global_nodes[-1]
        chunks.append({
            'type': 'global',
            'name': f"{os.path.basename(filepath)} (全局代码)",
            'code': code,
            'file': filepath,
            'start_line': first.lineno,
            'end_line': getattr(last, 'end_lineno', last.lineno),
            'module_docstring': module_doc,
            'docstring': '',
            'class_name': None,
            'struct_def': None,
        })
        global_nodes.clear()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _flush_global_nodes()
            line_count = _node_line_count(node)
            if line_count <= MAX_CHUNK_LINES:
                chunks.append({
                    'type': 'function',
                    'name': node.name,
                    'code': _extract_node_source(source_lines, node),
                    'file': filepath,
                    'start_line': node.lineno,
                    'end_line': node.end_lineno,
                    'module_docstring': module_doc,
                    'docstring': ast.get_docstring(node) or '',
                    'class_name': None,
                    'struct_def': None,
                })
            else:
                chunks.extend(_split_long_function(node, source_lines, filepath, module_doc))

        elif isinstance(node, ast.ClassDef):
            _flush_global_nodes()
            # 1. 类概览chunk
            overview = _extract_class_overview(node, source_lines)
            chunks.append({
                'type': 'class_overview',
                'name': f"{node.name} (概览)",
                'code': overview,
                'file': filepath,
                'start_line': node.lineno,
                'end_line': node.end_lineno,
                'module_docstring': module_doc,
                'docstring': ast.get_docstring(node) or '',
                'class_name': node.name,
                'struct_def': None,
            })

            # 2. 每个方法
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    line_count = _node_line_count(item)
                    if line_count <= MAX_CHUNK_LINES:
                        chunks.append({
                            'type': 'method',
                            'name': item.name,
                            'code': _extract_node_source(source_lines, item),
                            'file': filepath,
                            'start_line': item.lineno,
                            'end_line': item.end_lineno,
                            'module_docstring': module_doc,
                            'docstring': ast.get_docstring(item) or '',
                            'class_name': node.name,
                            'struct_def': overview,
                        })
                    else:
                        sub_chunks = _split_long_function(
                            item, source_lines, filepath, module_doc,
                            class_name=node.name
                        )
                        for c in sub_chunks:
                            c['struct_def'] = overview
                        chunks.extend(sub_chunks)

        elif _is_skip_global_node(node):
            # import、模块docstring → 跳过，不纳入全局代码
            continue

        else:
            # 收集全局语句（赋值、初始化、条件分支等）
            global_nodes.append(node)

    # 刷新尾部可能残留的全局语句
    _flush_global_nodes()

    # 空文件兜底
    if not chunks and source.strip():
        chunks.append({
            'type': 'file',
            'name': os.path.basename(filepath),
            'code': source,
            'file': filepath,
            'start_line': 1,
            'end_line': len(source_lines),
            'module_docstring': module_doc,
            'docstring': '',
            'class_name': None,
            'struct_def': None,
        })

    return chunks


# ============================================================
# 项目扫描
# ============================================================

def scan_project(root_dir, ignore_dirs, file_patterns, rag_dirs=None):
    """扫描项目文件，支持按 rag_dirs 限定索引范围。

    Args:
        root_dir: 项目根目录（绝对路径）
        ignore_dirs: 要忽略的目录名列表
        file_patterns: 文件扩展名匹配模式，如 ["*.py"]
        rag_dirs: 可选，只索引这些子目录（相对 root_dir），为空则索引全部
    """
    target_files = []

    if rag_dirs:
        # 只扫描指定的子目录
        for rag_dir in rag_dirs:
            scan_dir = os.path.join(root_dir, rag_dir)
            if not os.path.isdir(scan_dir):
                print(f"  警告: rag_dirs 中的目录不存在: {scan_dir}")
                continue
            for dirpath, dirnames, filenames in os.walk(scan_dir):
                dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
                for filename in filenames:
                    if any(filename.endswith(ext.replace('*', '')) for ext in file_patterns):
                        target_files.append(os.path.join(dirpath, filename))
    else:
        # 扫描全部目录
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs]
            for filename in filenames:
                if any(filename.endswith(ext.replace('*', '')) for ext in file_patterns):
                    target_files.append(os.path.join(dirpath, filename))

    return target_files


def chunk_project(config):
    root = config['project']['root']
    ignore = config['project']['ignore_dirs']
    patterns = config['project']['file_patterns']
    rag_dirs = config['project'].get('rag_dirs')

    files = scan_project(root, ignore, patterns, rag_dirs)
    print(f"扫描到 {len(files)} 个Python文件")

    # 归一化根目录为正斜杠，用于提取相对路径
    norm_root = root.replace('\\', '/').rstrip('/')

    all_chunks = []
    for filepath in files:
        try:
            chunks = extract_chunks(filepath)
            # 将绝对路径转为相对路径（正斜杠，跨平台通用）
            for chunk in chunks:
                abs_path = chunk['file'].replace('\\', '/')
                if abs_path.startswith(norm_root + '/'):
                    chunk['file'] = abs_path[len(norm_root) + 1:]
                elif abs_path.startswith(norm_root) and len(abs_path) > len(norm_root):
                    chunk['file'] = abs_path[len(norm_root):].lstrip('/')
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  跳过文件 {filepath}: {e}")

    print(f"共提取 {len(all_chunks)} 个代码块")
    return all_chunks


if __name__ == '__main__':
    import yaml
    with open('../config.yaml', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    chunks = chunk_project(config)
    with open('../data/chunks.json', 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"已保存到 data/chunks.json")
