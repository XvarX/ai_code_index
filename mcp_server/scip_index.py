"""
scip_index.py - SCIP 索引查询引擎
解析预构建的 SCIP 索引，提供代码导航查询（替代 LSP）
"""

import os
import sys
import json
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# 导入 protobuf 生成的代码
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)
from scip_pb2 import Index as ScipIndexProto

# Symbol roles (bitset)
ROLE_DEFINITION = 1
ROLE_IMPORT = 2
ROLE_WRITE_ACCESS = 4
ROLE_READ_ACCESS = 8


class SCIPIndex:
    """SCIP 索引的内存查询引擎"""

    def __init__(self):
        self.project_root = ""
        # symbol -> 定义信息 {file, line, char, display_name, kind}
        self.definitions = {}
        # symbol -> 所有 occurrence [{file, line, char, roles, enclosing_symbol}]
        self.occurrences = defaultdict(list)
        # file -> 该文件所有 occurrence
        self.file_occurrences = defaultdict(list)
        # file:line -> 最近的 symbol（用于位置查询）
        self.position_index = []  # [(file, start_line, start_char, end_line, end_char, symbol, roles)]
        # 调用图: symbol -> [被调用的 symbol]
        self.call_graph_outgoing = defaultdict(set)
        # 调用图: symbol -> [调用者 symbol]
        self.call_graph_incoming = defaultdict(set)
        # enclosing symbol -> (file, start_line, end_line) — 函数/方法的范围
        self.function_ranges = {}  # symbol -> {file, start_line, end_line}
        # 短名索引
        self.name_to_symbols = defaultdict(list)   # "CMonster" -> [full_symbol, ...]
        self.file_definitions = defaultdict(list)   # "gameplay/box.py" -> [{symbol, kind, line, name}]
        self.inheritance_parent = {}                # child_sym -> parent_sym
        self.inheritance_children = defaultdict(list)  # parent_sym -> [child_sym, ...]

    @staticmethod
    def _extract_short_name(symbol: str):
        """从 SCIP 符号提取短名和类型。
        Returns (short_name, kind) or (None, None)。
        """
        parts = symbol.split(' ')
        if len(parts) < 5:
            return None, None

        descriptor = parts[-1]

        # 取最后一个 '/' 之后的部分
        if '/' in descriptor:
            name_part = descriptor.rsplit('/', 1)[1]
        else:
            name_part = descriptor

        # 跳过参数 (filepath)
        if name_part.startswith('(') and name_part.endswith(')'):
            return None, None

        if name_part.endswith('#'):
            # 类定义: CBox#
            return name_part[:-1], 'class'
        elif '#' in name_part:
            # 方法: CBox#NewHour().
            # 也包括参数引用: CBox#NewHour().(param) -> 视为父方法
            class_name, rest = name_part.split('#', 1)
            method_name = rest.rstrip('.').split('(')[0]
            return f"{class_name}.{method_name}", 'method'
        elif name_part.endswith('().'):
            # 函数: check_file_exists().
            return name_part[:-3], 'function'
        elif name_part.endswith('.'):
            # 变量: config.
            return name_part[:-1], 'variable'
        elif name_part.endswith(':'):
            # 模块: __init__:
            return name_part[:-1], 'module'

        return None, None

    @staticmethod
    def _detect_path_prefix(proto_documents, project_root):
        """
        检测 scip-python 生成的路径是否有项目名前缀。

        scip-python 会索引 project_root 所在的整个 git 仓库，
        导致路径带有项目目录名前缀（如 testhd/gameplay/...）。
        本方法检测这种情况，返回需要过滤和剥离的前缀。

        Returns:
            (filter_prefix, should_strip) - 前缀字符串和是否需要剥离，无前缀时返回 ("", False)
        """
        if not project_root:
            return "", False

        project_name = os.path.basename(project_root.rstrip(os.sep))
        if not project_name:
            return "", False

        # 统计以 project_name/ 开头的文档数量
        prefix_slash = project_name + '/'
        prefix_backslash = project_name + '\\'
        matched = 0
        for doc in proto_documents:
            p = doc.relative_path
            if p.startswith(prefix_slash) or p.startswith(prefix_backslash):
                matched += 1

        # 如果有匹配的文档，说明 scip-python 从上级 git 仓库索引的
        if matched > 0:
            logger.info(f"SCIP 路径前缀检测: '{project_name}/' 前缀匹配 {matched} 个文档，将过滤并剥离")
            return prefix_slash, True

        return "", False

    @classmethod
    def from_file(cls, index_path: str, project_root: str = "", rag_dirs=None) -> 'SCIPIndex':
        """从 .scip protobuf 文件加载索引

        Args:
            index_path: .scip 文件路径
            project_root: 项目根目录
            rag_dirs: 可选，只加载这些子目录的索引（相对 project_root，如 ["gameplay", "scene/core"]）
        """
        self = cls()
        self.project_root = project_root

        proto = ScipIndexProto()
        with open(index_path, 'rb') as f:
            proto.ParseFromString(f.read())

        logger.info(f"SCIP 索引加载: {len(proto.documents)} 文档, {len(proto.external_symbols)} 外部符号")

        # 检测路径前缀（scip-python 可能从上级 git 仓库索引，导致路径带项目名前缀）
        filter_prefix, should_strip = self._detect_path_prefix(proto.documents, project_root)

        # 预处理 rag_dirs：统一为正斜杠，尾部加 / 用于前缀匹配
        rag_prefixes = None
        if rag_dirs:
            rag_prefixes = [d.replace('\\', '/').strip('/') + '/' for d in rag_dirs]
            logger.info(f"SCIP rag_dirs 过滤: {rag_prefixes}")

        skipped = 0
        for doc in proto.documents:
            raw_path = doc.relative_path

            # 过滤：跳过项目目录外的文件
            if should_strip:
                normalized = raw_path.replace('\\', '/')
                if not normalized.startswith(filter_prefix):
                    skipped += 1
                    continue
                # 剥离前缀，使路径相对于项目根目录
                raw_path = normalized[len(filter_prefix):]

            # 过滤：按 rag_dirs 限定范围
            if rag_prefixes:
                norm_rel = raw_path.replace('\\', '/')
                if not any(norm_rel.startswith(p) or norm_rel == p.rstrip('/') for p in rag_prefixes):
                    skipped += 1
                    continue

            rel_path = raw_path.replace('/', os.sep)

            # 处理 occurrences
            for occ in doc.occurrences:
                r = list(occ.range)
                start_line = r[0] if len(r) > 0 else 0
                start_char = r[1] if len(r) > 1 else 0
                # SCIP range 编码:
                #   3 元素: [startLine, startCharacter, endCharacter] (endLine=startLine)
                #   4 元素: [startLine, startCharacter, endLine, endCharacter]
                if len(r) == 3:
                    end_line = start_line
                    end_char = r[2]
                elif len(r) >= 4:
                    end_line = r[2]
                    end_char = r[3]
                else:
                    end_line = start_line
                    end_char = start_char

                is_def = bool(occ.symbol_roles & ROLE_DEFINITION)

                occ_info = {
                    'file': rel_path,
                    'line': start_line,      # 0-based
                    'char': start_char,
                    'end_line': end_line,
                    'end_char': end_char,
                    'symbol': occ.symbol,
                    'roles': occ.symbol_roles,
                    'is_definition': is_def,
                }

                # enclosing_range（同样的 3/4 元素编码）
                if occ.enclosing_range:
                    er = list(occ.enclosing_range)
                    enc_start_line = er[0] if len(er) > 0 else 0
                    if len(er) == 3:
                        enc_end_line = enc_start_line
                    elif len(er) >= 4:
                        enc_end_line = er[2]
                    else:
                        enc_end_line = enc_start_line
                    occ_info['enclosing_start_line'] = enc_start_line
                    occ_info['enclosing_end_line'] = enc_end_line

                self.occurrences[occ.symbol].append(occ_info)
                self.file_occurrences[rel_path].append(occ_info)

                # 位置索引（用于按位置查找 symbol）
                self.position_index.append((
                    rel_path, start_line, start_char,
                    end_line, end_char,
                    occ.symbol, occ.symbol_roles
                ))

                # 定义信息
                if is_def:
                    self.definitions[occ.symbol] = {
                        'file': rel_path,
                        'line': start_line,
                        'char': start_char,
                    }
                    # 短名索引
                    short_name, sym_kind = self._extract_short_name(occ.symbol)
                    if short_name:
                        self.name_to_symbols[short_name].append(occ.symbol)
                        # 跳过参数级定义 (method().(param))，只保留方法/类/函数/模块
                        is_param = ').(' in occ.symbol
                        if not is_param:
                            # 去重：避免同一文件同一位置重复添加
                            existing = self.file_definitions[rel_path]
                            if not any(d['line'] == start_line and d['name'] == short_name for d in existing):
                                existing.append({
                                    'symbol': occ.symbol,
                                    'kind': sym_kind,
                                    'line': start_line,
                                    'name': short_name,
                                })

                # 函数范围（用于调用图构建）
                if is_def and occ.enclosing_range:
                    er = list(occ.enclosing_range)
                    self.function_ranges[occ.symbol] = {
                        'file': rel_path,
                        'start_line': er[0],
                        'end_line': er[2] if len(er) > 2 else er[0],
                    }

            # 处理 symbols（relationships - 继承关系）
            for sym in doc.symbols:
                for rel in sym.relationships:
                    if rel.is_implementation:
                        self.inheritance_parent[sym.symbol] = rel.symbol
                        self.inheritance_children[rel.symbol].append(sym.symbol)

        # 构建调用图
        self._build_call_graphs()

        if skipped > 0:
            logger.info(f"SCIP 索引过滤: 跳过 {skipped} 个项目目录外的文件")

        logger.info(f"SCIP 索引就绪: {len(self.definitions)} 定义, "
                     f"{len(self.call_graph_outgoing)} 调用关系")
        return self

    def _normalize_file_path(self, file_path):
        """将各种格式的文件路径归一化为索引中存储的格式（相对路径 + os.sep）。

        处理场景：
        - 绝对路径: D:\\space\\...\\testhd\\gameplay\\box.py
        - 带项目名前缀: testhd/gameplay/box.py
        - 正斜杠相对路径: gameplay/box.py
        """
        if not file_path:
            return file_path

        project_root = self.project_root
        if not project_root:
            return file_path.replace('/', os.sep)

        norm_file = file_path.replace('\\', '/')
        norm_root = project_root.replace('\\', '/').rstrip('/')
        project_name = os.path.basename(norm_root)

        # 绝对路径：去掉项目根目录前缀
        if norm_file.startswith(norm_root + '/'):
            rel = norm_file[len(norm_root) + 1:]
            return rel.replace('/', os.sep)

        # 带项目名前缀的相对路径: testhd/gameplay/box.py -> gameplay/box.py
        prefix = project_name + '/'
        if project_name and norm_file.startswith(prefix):
            rel = norm_file[len(prefix):]
            return rel.replace('/', os.sep)

        # 绝对路径中包含项目名: /home/user/testhd/gameplay/box.py -> gameplay/box.py
        marker = '/' + project_name + '/'
        if project_name and marker in norm_file:
            idx = norm_file.find(marker)
            rel = norm_file[idx + len(marker):]
            return rel.replace('/', os.sep)

        # 普通相对路径: gameplay/box.py -> gameplay\\box.py
        return file_path.replace('/', os.sep)

    def _build_call_graphs(self):
        """从函数范围构建调用图

        scip-python 生成的非定义 occurrence 不携带 enclosing_range，
        因此用 occurrence 自身的行号去匹配函数范围，确定调用关系。
        只追踪函数/方法级别的调用（被引用的符号本身需是函数/方法）。
        """
        # 建立函数范围查找表: (file, start_line, end_line, symbol)
        func_lookup = []
        for sym, info in self.function_ranges.items():
            func_lookup.append((info['file'], info['start_line'], info['end_line'], sym))
        # 按文件和起始行排序
        func_lookup.sort()

        for symbol, occs in self.occurrences.items():
            for occ in occs:
                if occ['is_definition']:
                    continue
                # 只追踪函数/方法级别的调用（被引用的符号本身是函数/方法）
                if symbol not in self.function_ranges:
                    continue

                # 用 occurrence 自身的行号查找包含它的函数
                file = occ['file']
                line = occ['line']

                # 在 func_lookup 中查找
                enclosing_sym = None
                for f_file, f_start, f_end, f_sym in func_lookup:
                    if f_file == file and f_start <= line <= f_end:
                        enclosing_sym = f_sym
                        break

                if enclosing_sym and enclosing_sym != symbol:
                    self.call_graph_outgoing[enclosing_sym].add(symbol)
                    self.call_graph_incoming[symbol].add(enclosing_sym)

    def _find_symbol_at(self, file: str, line: int, column: int = 0):
        """查找 file:line:column 处的 symbol。line 为 1-based。"""
        file_normalized = file.replace('/', os.sep)
        line_0 = line - 1  # 转为 0-based

        best = None
        best_size = float('inf')
        best_resolved = None
        best_resolved_size = float('inf')

        for f, sl, sc, el, ec, sym, roles in self.position_index:
            if f != file_normalized:
                continue
            if sl <= line_0 <= el:
                # 检查 column（如果在范围内）
                if line_0 == sl and column > 0 and column - 1 < sc:
                    continue
                size = (el - sl) * 10000 + (ec - sc)
                if size < best_size:
                    best_size = size
                    best = sym
                # 优先记录有有效短名的符号
                if size < best_resolved_size:
                    short_name, _ = self._extract_short_name(sym)
                    if short_name:
                        best_resolved_size = size
                        best_resolved = sym

        # 优先返回已解析符号（有有效短名），否则回退到最小范围
        return best_resolved if best_resolved is not None else best

    def get_definition(self, file: str, line: int, column: int = 0) -> str:
        """跳转到定义。等价 LSP textDocument/definition"""
        file = self._normalize_file_path(file)
        symbol = self._find_symbol_at(file, line, column)
        if not symbol:
            return json.dumps({"error": "未找到符号"}, ensure_ascii=False)

        defn = self.definitions.get(symbol)
        if not defn:
            # 可能是外部符号
            return json.dumps({"error": f"未找到定义: {symbol}"}, ensure_ascii=False)

        # 返回与 LSP 相同的格式
        abs_path = os.path.join(self.project_root, defn['file'])
        result = [{
            "uri": f"file:///{abs_path.replace(os.sep, '/')}",
            "range": {
                "start": {"line": defn['line'], "character": defn['char']},
                "end": {"line": defn['line'], "character": defn['char'] + 20}
            }
        }]
        return json.dumps(result, ensure_ascii=False, indent=2)

    def find_references(self, file: str, line: int) -> str:
        """查找所有引用。等价 LSP textDocument/references"""
        file = self._normalize_file_path(file)
        symbol = self._find_symbol_at(file, line)
        if not symbol:
            return json.dumps({"error": "未找到符号"}, ensure_ascii=False)

        occs = self.occurrences.get(symbol, [])
        locations = []
        for occ in occs:
            # 1-based line
            locations.append(f"{occ['file']}:{occ['line'] + 1}")

        if not locations:
            return json.dumps({"error": "未找到引用"}, ensure_ascii=False)

        return json.dumps(locations, ensure_ascii=False, indent=2)

    def get_call_chain(self, file: str, line: int, direction: str = "outgoing") -> list:
        """获取调用链。等价 LSP callHierarchy"""
        file = self._normalize_file_path(file)
        symbol = self._find_symbol_at(file, line)
        if not symbol:
            return json.dumps({"error": "未找到符号"}, ensure_ascii=False)

        if direction == "outgoing":
            callees = self.call_graph_outgoing.get(symbol, set())
        else:
            callees = self.call_graph_incoming.get(symbol, set())

        result = []
        for callee_sym in callees:
            defn = self.definitions.get(callee_sym)
            if defn:
                # 提取简短名称
                name = callee_sym.split('(')[0].split('.')[-1] if callee_sym else '?'
                result.append({
                    "file": defn['file'],
                    "line": defn['line'] + 1,  # 1-based
                    "name": name,
                })

        if not result:
            return json.dumps([], ensure_ascii=False)

        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_module_call_graph(self, module_path: str) -> dict:
        """获取模块内所有函数的调用关系（构建阶段用）"""
        module_prefix = module_path.replace('/', os.sep)

        graph = defaultdict(list)
        for func_sym, callees in self.call_graph_outgoing.items():
            defn = self.definitions.get(func_sym)
            if not defn:
                continue
            # 只取指定模块内的函数
            if not defn['file'].startswith(module_prefix):
                continue

            key = f"{defn['file']}:{defn['line'] + 1}"
            for callee_sym in callees:
                callee_defn = self.definitions.get(callee_sym)
                if callee_defn:
                    name = callee_sym.split('(')[0].split('.')[-1]
                    graph[key].append(f"{callee_defn['file']}:{callee_defn['line'] + 1} ({name})")

        return dict(graph)

    def search_symbol(self, name: str, kind: str = "") -> str:
        """按短名搜索符号定义（类名/函数名），比 RAG 更快更精确"""
        symbols = self.name_to_symbols.get(name, [])
        if not symbols:
            return json.dumps({"error": f"未找到符号: {name}"}, ensure_ascii=False)

        useful_kinds = {'class', 'method', 'function'}
        results = []
        for sym in symbols:
            defn = self.definitions.get(sym)
            if not defn:
                continue
            short_name, sym_kind = self._extract_short_name(sym)
            if kind and sym_kind != kind:
                continue
            if not kind and sym_kind not in useful_kinds:
                continue
            results.append({
                "name": short_name or name,
                "file": defn['file'],
                "line": defn['line'] + 1,
                "kind": sym_kind,
            })

        return json.dumps(results, ensure_ascii=False, indent=2)

    def list_symbols(self, file: str, kind: str = "") -> str:
        """列出文件中所有类和方法定义"""
        file_normalized = self._normalize_file_path(file)
        defs = self.file_definitions.get(file_normalized, [])

        if not defs:
            return json.dumps({"error": f"未找到文件: {file}"}, ensure_ascii=False)

        # 默认只返回 class 和 method/function，跳过 variable/module
        useful_kinds = {'class', 'method', 'function'}
        results = []
        for d in defs:
            if kind and d['kind'] != kind:
                continue
            if not kind and d['kind'] not in useful_kinds:
                continue
            results.append({
                "name": d['name'],
                "file": file_normalized,
                "line": d['line'] + 1,
                "kind": d['kind'],
            })

        return json.dumps(results, ensure_ascii=False)

    def module_overview(self, module_path: str) -> str:
        """列出模块中所有类和顶层函数"""
        module_prefix = self._normalize_file_path(module_path)

        classes = []
        functions = []

        for file_path, defs in self.file_definitions.items():
            if not file_path.startswith(module_prefix):
                continue
            for d in defs:
                if d['kind'] == 'class':
                    classes.append({
                        "name": d['name'],
                        "file": file_path,
                        "line": d['line'] + 1,
                    })
                elif d['kind'] == 'function':
                    functions.append({
                        "name": d['name'],
                        "file": file_path,
                        "line": d['line'] + 1,
                    })

        return json.dumps({
            "classes": classes,
            "functions": functions,
        }, ensure_ascii=False, indent=2)

    def find_inheritance(self, name: str, direction: str = "parent") -> str:
        """查找类的继承关系"""
        symbols = self.name_to_symbols.get(name, [])
        class_symbols = [sym for sym in symbols
                         if self._extract_short_name(sym)[1] == 'class']

        if not class_symbols:
            return json.dumps({"error": f"未找到类: {name}"}, ensure_ascii=False)

        results = []
        for sym in class_symbols:
            if direction == "parent":
                parent = self.inheritance_parent.get(sym)
                if parent:
                    defn = self.definitions.get(parent)
                    parent_name, _ = self._extract_short_name(parent)
                    results.append({
                        "parent": parent_name or parent,
                        "file": defn['file'] if defn else "",
                        "line": defn['line'] + 1 if defn else 0,
                    })
            else:
                children = self.inheritance_children.get(sym, [])
                for child_sym in children:
                    defn = self.definitions.get(child_sym)
                    child_name, _ = self._extract_short_name(child_sym)
                    results.append({
                        "child": child_name or child_sym,
                        "file": defn['file'] if defn else "",
                        "line": defn['line'] + 1 if defn else 0,
                    })

        return json.dumps(results, ensure_ascii=False, indent=2)
