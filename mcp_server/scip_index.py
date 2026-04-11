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

    @classmethod
    def from_file(cls, index_path: str, project_root: str = "") -> 'SCIPIndex':
        """从 .scip protobuf 文件加载索引"""
        self = cls()
        self.project_root = project_root

        proto = ScipIndexProto()
        with open(index_path, 'rb') as f:
            proto.ParseFromString(f.read())

        logger.info(f"SCIP 索引加载: {len(proto.documents)} 文档, {len(proto.external_symbols)} 外部符号")

        for doc in proto.documents:
            rel_path = doc.relative_path.replace('/', os.sep)

            # 处理 occurrences
            for occ in doc.occurrences:
                r = list(occ.range)
                start_line = r[0] if len(r) > 0 else 0
                start_char = r[1] if len(r) > 1 else 0
                end_line = r[2] if len(r) > 2 else start_line
                end_char = r[3] if len(r) > 3 else start_char

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

                # enclosing_range
                if occ.enclosing_range:
                    er = list(occ.enclosing_range)
                    occ_info['enclosing_start_line'] = er[0] if len(er) > 0 else 0
                    occ_info['enclosing_end_line'] = er[2] if len(er) > 2 else er[0] if len(er) > 0 else 0

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

                # 函数范围（用于调用图构建）
                if is_def and occ.enclosing_range:
                    er = list(occ.enclosing_range)
                    self.function_ranges[occ.symbol] = {
                        'file': rel_path,
                        'start_line': er[0],
                        'end_line': er[2] if len(er) > 2 else er[0],
                    }

            # 处理 symbols（relationships）
            for sym in doc.symbols:
                for rel in sym.relationships:
                    if rel.is_reference:
                        # symbol -> 被引用的 symbol
                        pass
                    if rel.is_implementation:
                        # symbol -> 实现者
                        pass

        # 构建调用图
        self._build_call_graphs()

        logger.info(f"SCIP 索引就绪: {len(self.definitions)} 定义, "
                     f"{len(self.call_graph_outgoing)} 调用关系")
        return self

    def _build_call_graphs(self):
        """从 enclosing_range 构建调用图"""
        # 建立函数范围查找表: (file, line) -> enclosing symbol
        func_lookup = []
        for sym, info in self.function_ranges.items():
            func_lookup.append((info['file'], info['start_line'], info['end_line'], sym))
        # 按文件和起始行排序
        func_lookup.sort()

        for symbol, occs in self.occurrences.items():
            for occ in occs:
                if occ['is_definition']:
                    continue
                if 'enclosing_start_line' not in occ:
                    continue

                # 找到包含此 occurrence 的函数
                file = occ['file']
                line = occ['enclosing_start_line']

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

        return best

    def get_definition(self, file: str, line: int, column: int = 0) -> str:
        """跳转到定义。等价 LSP textDocument/definition"""
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
