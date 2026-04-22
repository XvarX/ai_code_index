"""
lsp_client.py - LSP 实时查询客户端
通过 pyright-langserver 提供代码导航功能，替代 SCIP 离线索引

功能：
  - search_symbol: workspace/symbol
  - list_symbols: textDocument/documentSymbol
  - module_overview: documentSymbol × 多文件聚合
  - goto_definition: textDocument/definition
  - find_references: textDocument/references
  - get_call_chain: textDocument/prepareCallHierarchy + incomingCalls/outgoingCalls
  - find_inheritance: AST 解析（LSP 无直接方法）
"""

import ast
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# LSP SymbolKind 映射
SYMBOL_KIND_MAP = {
    5: 'class',     # Class
    6: 'method',    # Method
    12: 'function', # Function
    13: 'variable', # Variable
}

# kind 参数 -> LSP SymbolKind 过滤
KIND_FILTER = {
    'class': {5},
    'method': {6},
    'function': {12, 6},  # pylsp 可能把顶层函数标为 method
}


class LSPClient:
    """基于 pyright-langserver 的 LSP 查询客户端"""

    def __init__(self, project_root, lsp_config=None):
        self.project_root = os.path.abspath(project_root)
        self.lsp_config = lsp_config or {}
        self.process = None
        self.request_id = 0
        self._started = False
        self._lock = threading.Lock()  # 保护 _send/_read 的线程安全
        self._open_files = set()       # 已打开文件的相对路径
        self._file_contents = {}       # 缓存文件内容
        self._ignore_dirs = {'__pycache__', '.git', 'venv', 'env', 'node_modules', '.idea', '.vscode'}
        # AST 符号索引（search_symbol 用，因为 pyright 的 workspace/symbol 不可靠）
        self._symbol_index = None      # {short_name: [(file, line, kind), ...]}

    # ================================================================
    # 进程管理
    # ================================================================

    def _ensure_started(self):
        """懒启动 LSP 服务器"""
        if self._started:
            return self.process is not None

        self._started = True
        server_cmd = self.lsp_config.get('command', 'pyright-langserver')

        try:
            self.process = subprocess.Popen(
                [server_cmd, '--stdio'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.project_root,
            )
            time.sleep(0.3)
            if self.process.poll() is not None:
                logger.error(f"LSP 进程启动失败，退出码: {self.process.returncode}")
                self.process = None
                return False
        except FileNotFoundError:
            logger.error(f"LSP 服务器未找到: {server_cmd}")
            logger.error("  请安装: pip install pyright")
            self.process = None
            return False

        # initialize 握手
        timeout = self.lsp_config.get('timeout', 30)
        result = self._send('initialize', {
            'processId': None,
            'rootUri': Path(self.project_root).as_uri(),
            'capabilities': {
                'textDocument': {
                    'definition': {'dynamicRegistration': False},
                    'references': {'dynamicRegistration': False},
                    'documentSymbol': {
                        'dynamicRegistration': False,
                        'hierarchicalDocumentSymbolSupport': True,
                    },
                    'prepareCallHierarchy': {'dynamicRegistration': False},
                },
                'workspace': {
                    'symbol': {'dynamicRegistration': False},
                },
            },
        })

        if result is None:
            logger.error("LSP initialize 超时或失败")
            self._kill_process()
            return False

        # initialized 通知
        self._notify('initialized', {})
        logger.info(f"LSP 服务器就绪: {server_cmd}")
        return True

    def shutdown(self):
        """优雅关闭 LSP 服务器"""
        if not self.process:
            return
        try:
            self._send('shutdown', None, timeout=3)
            self._notify('exit', {})
        except Exception:
            pass
        self._kill_process()

    def _kill_process(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    # ================================================================
    # JSON-RPC 通信
    # ================================================================

    def _send(self, method, params, timeout=30):
        """发送 JSON-RPC 请求并等待响应"""
        if not self.process:
            return None

        with self._lock:
            self.request_id += 1
            rid = self.request_id
            msg = {
                'jsonrpc': '2.0',
                'id': rid,
                'method': method,
                'params': params or {},
            }
            body = json.dumps(msg)
            header = f'Content-Length: {len(body)}\r\n\r\n'
            try:
                self.process.stdin.write(header.encode() + body.encode())
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                logger.error("LSP 进程通信断开")
                self._kill_process()
                return None

            return self._read_response(rid, timeout)

    def _notify(self, method, params):
        """发送 JSON-RPC 通知（无 id，不等响应）"""
        if not self.process:
            return
        msg = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
        }
        body = json.dumps(msg)
        header = f'Content-Length: {len(body)}\r\n\r\n'
        try:
            self.process.stdin.write(header.encode() + body.encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _read_response(self, expected_id, timeout=30):
        """读取 LSP 响应，跳过通知消息，按 id 匹配"""
        import time as _time
        deadline = _time.time() + timeout

        while _time.time() < deadline:
            # 读 Content-Length 头
            headers = {}
            while True:
                try:
                    line = self.process.stdout.readline()
                except Exception:
                    return None
                if not line:
                    return None
                if line in (b'\r\n', b'\n'):
                    break
                if b':' in line:
                    key, val = line.decode('ascii', errors='replace').split(':', 1)
                    headers[key.strip()] = val.strip()

            length = int(headers.get('Content-Length', '0'))
            if length == 0:
                continue

            body = self.process.stdout.read(length)
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                continue

            # 如果是通知（没有 id 或有 method），跳过
            if 'id' not in msg:
                continue
            if msg.get('method'):
                continue

            # 匹配期望的 id
            if msg['id'] == expected_id:
                if 'error' in msg:
                    logger.warning(f"LSP 错误: {msg['error']}")
                    return None
                return msg.get('result')

        logger.warning(f"LSP 响应超时 (id={expected_id})")
        return None

    # ================================================================
    # 文件管理
    # ================================================================

    def _file_uri(self, rel_path):
        """相对路径 -> file:/// URI"""
        abs_path = os.path.normpath(os.path.join(self.project_root, rel_path))
        return Path(abs_path).as_uri()

    def _rel_path(self, uri):
        """file:/// URI -> 相对路径（正斜杠）"""
        if not uri:
            return ''
        parsed = urlparse(uri)
        abs_path = unquote(parsed.path)
        # Windows: /D:/path -> D:/path
        if sys.platform == 'win32' and abs_path.startswith('/') and len(abs_path) > 2 and abs_path[2] == ':':
            abs_path = abs_path[1:]
        try:
            rel = os.path.relpath(abs_path, self.project_root)
        except ValueError:
            return abs_path.replace('\\', '/')
        return rel.replace('\\', '/')

    def _open_file(self, rel_path):
        """打开文件（如果尚未打开）"""
        if rel_path in self._open_files:
            return True

        full_path = os.path.join(self.project_root, rel_path)
        if not os.path.exists(full_path):
            return False

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return False

        self._notify('textDocument/didOpen', {
            'textDocument': {
                'uri': self._file_uri(rel_path),
                'languageId': 'python',
                'version': 1,
                'text': content,
            }
        })
        self._open_files.add(rel_path)
        self._file_contents[rel_path] = content
        return True

    def _read_file_content(self, rel_path):
        """读取文件内容（优先缓存）"""
        if rel_path in self._file_contents:
            return self._file_contents[rel_path]
        full_path = os.path.join(self.project_root, rel_path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ''

    # ================================================================
    # 工具方法（与 SCIP 工具签名一致）
    # ================================================================

    def _build_symbol_index(self):
        """用 AST 扫描项目文件，构建符号索引（用于 search_symbol）"""
        from collections import defaultdict
        index = defaultdict(list)  # short_name -> [(file, line, kind)]

        for dirpath, dirnames, filenames in os.walk(self.project_root):
            dirnames[:] = [d for d in dirnames if d not in self._ignore_dirs
                           and not d.startswith('.')]
            for fn in filenames:
                if not fn.endswith('.py'):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.project_root).replace('\\', '/')
                try:
                    with open(full, 'r', encoding='utf-8') as f:
                        source = f.read()
                    tree = ast.parse(source)
                except (SyntaxError, Exception):
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        index[node.name].append((rel, node.lineno, 'class'))
                        # 也索引 ClassName.method_name
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                short = f"{node.name}.{item.name}"
                                index[short].append((rel, item.lineno, 'method'))
                                # 纯方法名也索引（模糊匹配用）
                                index[item.name].append((rel, item.lineno, 'method'))
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # 顶层函数（不在类中的）— 通过检查 col_offset == 0 判断
                        if hasattr(node, 'col_offset') and node.col_offset == 0:
                            index[node.name].append((rel, node.lineno, 'function'))

        self._symbol_index = dict(index)
        logger.info(f"AST 符号索引就绪: {len(self._symbol_index)} 个短名")

    def search_symbol(self, name, kind=""):
        """按名称搜索符号定义

        支持三种搜索方式：
        1. 精确匹配: search_symbol("MonsterManager") -> 类
        2. 类.方法: search_symbol("MonsterManager.spawn_monster") -> 方法
        3. 纯方法名: search_symbol("spawn_monster") -> 模糊匹配所有
        """
        # 懒构建 AST 符号索引
        if self._symbol_index is None:
            self._build_symbol_index()

        # 精确查找
        matches = self._symbol_index.get(name, [])

        # 精确匹配失败且不是类.方法格式，尝试后缀模糊匹配
        if not matches and '.' not in name:
            suffix = '.' + name
            for key, entries in self._symbol_index.items():
                if key.endswith(suffix):
                    matches.extend(entries)

        if not matches:
            return json.dumps({"error": f"未找到符号: {name}"}, ensure_ascii=False)

        useful_kinds = {'class', 'method', 'function'}
        seen = set()
        results = []

        for file_path, line, sym_kind in matches:
            # kind 过滤
            if kind and sym_kind != kind:
                continue
            if not kind and sym_kind not in useful_kinds:
                continue

            key = (file_path, line)
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "name": name if '.' not in name else name,
                "file": file_path,
                "line": line,
                "kind": sym_kind,
            })

        if not results:
            return json.dumps({"error": f"未找到符号: {name}"}, ensure_ascii=False)

        return json.dumps(results, ensure_ascii=False, indent=2)

    def list_symbols(self, file, kind=""):
        """列出文件中所有类和方法定义"""
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"}, ensure_ascii=False)

        if not self._open_file(file):
            return json.dumps({"error": f"文件不存在: {file}"}, ensure_ascii=False)

        result = self._send('textDocument/documentSymbol', {
            'textDocument': {'uri': self._file_uri(file)},
        })

        if not result:
            return json.dumps({"error": f"未找到文件: {file}"}, ensure_ascii=False)

        useful_kinds = {'class', 'method', 'function'}
        results = []

        def _flatten_symbols(symbols, parent_class=None):
            for sym in symbols:
                name = sym.get('name', '')
                kind_num = sym.get('kind', 0)
                kind_str = SYMBOL_KIND_MAP.get(kind_num, '')

                if kind_str in useful_kinds or (kind and kind_str == kind):
                    rng = sym.get('range', sym.get('selectionRange', {}))
                    line = rng.get('start', {}).get('line', 0) + 1
                    results.append({
                        "name": name,
                        "file": file,
                        "line": line,
                        "kind": kind_str,
                    })

                # 递归子符号（类中的方法）
                children = sym.get('children', [])
                if children:
                    _flatten_symbols(children, parent_class=name)

        _flatten_symbols(result if isinstance(result, list) else [])

        # kind 过滤
        if kind:
            kind_set = KIND_FILTER.get(kind, set())
            results = [r for r in results if SYMBOL_KIND_MAP.get(
                {v: k for k, v in SYMBOL_KIND_MAP.items()}.get(r['kind'], 0), ''
            ) == kind or r['kind'] == kind]

        return json.dumps(results, ensure_ascii=False)

    def module_overview(self, module_path):
        """列出模块中所有类和顶层函数"""
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"}, ensure_ascii=False)

        module_dir = os.path.join(self.project_root, module_path.replace('/', os.sep))
        if not os.path.isdir(module_dir):
            # 可能是单文件模块
            single_file = module_path if '.' not in module_path else module_path
            if os.path.isfile(os.path.join(self.project_root, single_file)):
                return self._symbols_for_files([single_file])
            return json.dumps({"classes": [], "functions": []}, ensure_ascii=False)

        # 收集模块下所有 .py 文件
        py_files = []
        for dirpath, dirnames, filenames in os.walk(module_dir):
            dirnames[:] = [d for d in dirnames if d not in self._ignore_dirs
                           and not d.startswith('.') and d != '__pycache__']
            for fn in filenames:
                if fn.endswith('.py'):
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, self.project_root).replace('\\', '/')
                    py_files.append(rel)

        return self._symbols_for_files(py_files)

    def _symbols_for_files(self, files):
        """从多个文件中聚合类和函数"""
        classes = []
        functions = []

        for file_path in files:
            if not self._open_file(file_path):
                continue

            result = self._send('textDocument/documentSymbol', {
                'textDocument': {'uri': self._file_uri(file_path)},
            })

            if not result:
                continue

            def _extract(symbols):
                for sym in symbols:
                    name = sym.get('name', '')
                    kind_num = sym.get('kind', 0)
                    kind_str = SYMBOL_KIND_MAP.get(kind_num, '')
                    rng = sym.get('range', sym.get('selectionRange', {}))
                    line = rng.get('start', {}).get('line', 0) + 1

                    if kind_str == 'class':
                        classes.append({"name": name, "file": file_path, "line": line})
                    elif kind_str == 'function':
                        functions.append({"name": name, "file": file_path, "line": line})
                    elif kind_str == 'method':
                        # 顶层方法也当作函数
                        functions.append({"name": name, "file": file_path, "line": line})

                    children = sym.get('children', [])
                    if children:
                        _extract(children)

            _extract(result if isinstance(result, list) else [])

        return json.dumps({
            "classes": classes,
            "functions": functions,
        }, ensure_ascii=False, indent=2)

    def find_inheritance(self, name, direction="parent"):
        """查找类的继承关系（纯 AST 实现，不依赖 LSP）"""
        # 用 AST 符号索引找到类定义位置（workspace/symbol 在 pyright 中不可靠）
        if self._symbol_index is None:
            self._build_symbol_index()

        class_files = {}  # file -> line
        matches = self._symbol_index.get(name, [])
        for file_path, line, kind in matches:
            if kind == 'class':
                class_files[file_path] = line

        if not class_files:
            return json.dumps({"error": f"未找到类: {name}"}, ensure_ascii=False)

        if direction == "parent":
            return self._find_parent(name, class_files)
        else:
            return self._find_children(name, class_files)

    def _find_parent(self, name, class_files):
        """AST 方式查找父类"""
        results = []
        for file_path, line in class_files.items():
            content = self._read_file_content(file_path)
            if not content:
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == name:
                    for base in node.bases:
                        parent_name = self._get_name_from_node(base)
                        if parent_name:
                            # 用 workspace/symbol 找父类位置
                            parent_file, parent_line = self._find_class_location(parent_name)
                            results.append({
                                "parent": parent_name,
                                "file": parent_file,
                                "line": parent_line,
                            })

        if not results:
            return json.dumps([], ensure_ascii=False)
        return json.dumps(results, ensure_ascii=False, indent=2)

    def _find_children(self, name, class_files):
        """AST 方式查找子类"""
        results = []
        # 扫描项目所有 .py 文件
        for dirpath, dirnames, filenames in os.walk(self.project_root):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')
                           and d != '__pycache__' and d != '.git']
            for fn in filenames:
                if not fn.endswith('.py'):
                    continue
                full = os.path.join(dirpath, fn)
                file_path = os.path.relpath(full, self.project_root).replace('\\', '/')
                content = self._read_file_content(file_path)
                if not content:
                    continue
                try:
                    tree = ast.parse(content)
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        for base in node.bases:
                            base_name = self._get_name_from_node(base)
                            if base_name == name and node.name != name:
                                results.append({
                                    "child": node.name,
                                    "file": file_path,
                                    "line": node.lineno,
                                })

        if not results:
            return json.dumps([], ensure_ascii=False)
        return json.dumps(results, ensure_ascii=False, indent=2)

    def _find_class_location(self, class_name):
        """通过 AST 符号索引查找类定义位置"""
        if self._symbol_index is None:
            self._build_symbol_index()
        matches = self._symbol_index.get(class_name, [])
        for file_path, line, kind in matches:
            if kind == 'class':
                return file_path, line
        return "", 0

    @staticmethod
    def _get_name_from_node(node):
        """从 AST 节点提取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{LSPClient._get_name_from_node(node.value)}.{node.attr}"
        elif isinstance(node, ast.Constant):
            return str(node.value)
        return None

    def _find_symbol_position(self, file, line):
        """找到文件中指定行上符号的精确列位置。

        LSP 的 definition/references/callHierarchy 需要指向符号名的位置，
        而不是行首。此方法通过 documentSymbol 查找精确位置。
        优先使用 selectionRange（符号名位置），回退到 range（定义范围）。
        返回 (line_0based, character) 或 (line-1, 0) 作为回退。
        """
        if not self._open_file(file):
            return line - 1, 0

        result = self._send('textDocument/documentSymbol', {
            'textDocument': {'uri': self._file_uri(file)},
        })

        if not result:
            return line - 1, 0

        target_line = line - 1  # 0-based

        def _search(symbols):
            for sym in symbols:
                # 优先用 selectionRange（符号名的精确位置）
                sel_rng = sym.get('selectionRange', sym.get('range', {}))
                sel_start = sel_rng.get('start', {})
                if sel_start.get('line') == target_line:
                    return sel_start.get('character', 0)
                # 回退到 range
                rng = sym.get('range', {})
                rng_start = rng.get('start', {})
                if rng_start.get('line') == target_line:
                    # range 起始行匹配但 selectionRange 不匹配——检查 children
                    pass
                children = sym.get('children', [])
                if children:
                    found = _search(children)
                    if found is not None:
                        return found
            return None

        char = _search(result if isinstance(result, list) else [])
        if char is not None:
            return target_line, char
        return target_line, 0

    def get_definition(self, file, line, column=0):
        """跳转到定义"""
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"}, ensure_ascii=False)

        if not self._open_file(file):
            return json.dumps({"error": f"文件不存在: {file}"}, ensure_ascii=False)

        # 如果没有指定列，自动查找精确位置
        if column == 0:
            l, c = self._find_symbol_position(file, line)
        else:
            l, c = line - 1, column

        result = self._send('textDocument/definition', {
            'textDocument': {'uri': self._file_uri(file)},
            'position': {'line': l, 'character': c},
        })

        if not result:
            return json.dumps({"error": "未找到定义"}, ensure_ascii=False)

        # result 可能是 Location[] 或 LocationLink[]
        locations = []
        if isinstance(result, list):
            locations = result
        elif isinstance(result, dict):
            # LocationLink
            if 'targetUri' in result:
                locations = [{'uri': result['targetUri'],
                              'range': result.get('targetRange', {})}]
            else:
                locations = [result]

        if not locations:
            return json.dumps({"error": "未找到定义"}, ensure_ascii=False)

        output = []
        for loc in locations:
            uri = loc.get('uri', '')
            abs_path = self._uri_to_abs(uri)
            output.append({
                "uri": f"file:///{abs_path.replace(os.sep, '/')}",
                "range": loc.get('range', {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                }),
            })

        return json.dumps(output, ensure_ascii=False, indent=2)

    def find_references(self, file, line):
        """查找所有引用"""
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"}, ensure_ascii=False)

        if not self._open_file(file):
            return json.dumps({"error": f"文件不存在: {file}"}, ensure_ascii=False)

        l, c = self._find_symbol_position(file, line)

        result = self._send('textDocument/references', {
            'textDocument': {'uri': self._file_uri(file)},
            'position': {'line': l, 'character': c},
            'context': {'includeDeclaration': True},
        })

        if not result:
            return json.dumps({"error": "未找到引用"}, ensure_ascii=False)

        locations = []
        for ref in (result if isinstance(result, list) else []):
            uri = ref.get('uri', '')
            file_path = self._rel_path(uri)
            ln = ref.get('range', {}).get('start', {}).get('line', 0) + 1
            locations.append(f"{file_path}:{ln}")

        if not locations:
            return json.dumps({"error": "未找到引用"}, ensure_ascii=False)

        return json.dumps(locations, ensure_ascii=False, indent=2)

    def get_call_chain(self, file, line, direction="outgoing"):
        """获取调用链（call hierarchy）"""
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"}, ensure_ascii=False)

        if not self._open_file(file):
            return json.dumps({"error": f"文件不存在: {file}"}, ensure_ascii=False)

        l, c = self._find_symbol_position(file, line)
        uri = self._file_uri(file)

        # Step 1: prepareCallHierarchy
        items = self._send('textDocument/prepareCallHierarchy', {
            'textDocument': {'uri': uri},
            'position': {'line': l, 'character': c},
        })

        if not items:
            return json.dumps([], ensure_ascii=False)

        if not isinstance(items, list):
            items = [items]

        # Step 2: incomingCalls / outgoingCalls
        method = 'callHierarchy/incomingCalls' if direction == 'incoming' else 'callHierarchy/outgoingCalls'
        results = []

        for item in items:
            call_result = self._send(method, {'item': item}, timeout=15)
            if not call_result:
                continue

            for call in (call_result if isinstance(call_result, list) else []):
                # incomingCalls 用 'from'，outgoingCalls 用 'to'
                target = call.get('from' if direction == 'incoming' else 'to', {})
                target_uri = target.get('uri', '')
                target_file = self._rel_path(target_uri)
                target_line = target.get('range', {}).get('start', {}).get('line', 0) + 1
                target_name = target.get('name', '')

                results.append({
                    "file": target_file,
                    "line": target_line,
                    "name": target_name,
                })

        return json.dumps(results, ensure_ascii=False, indent=2)

    # ================================================================
    # 辅助
    # ================================================================

    def _uri_to_abs(self, uri):
        """file:/// URI -> 绝对路径"""
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if sys.platform == 'win32' and path.startswith('/') and len(path) > 2 and path[2] == ':':
            path = path[1:]
        return path
