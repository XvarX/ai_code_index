"""
rag_search.py - RAG查询实现
结构化查询 + 语义搜索（通过 Embedding API）
"""

import json
import os
import lancedb
from openai import OpenAI


class RAGSearcher:
    def __init__(self, config):
        db_path = config.get('db_path', '')
        if not os.path.isabs(db_path):
            # 基于本文件位置算绝对路径: mcp_server/../data/lancedb
            here = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.normpath(os.path.join(here, '..', 'data', 'lancedb'))
        self.db = lancedb.connect(db_path)
        self.table = self.db.open_table("game_server_code")

        self.embed_client = OpenAI(
            api_key=config['embedding'].get('api_key') or os.getenv('OPENAI_API_KEY'),
            base_url=config['embedding']['base_url'],
        )
        self.embed_model = config['embedding']['model']

    def _embed_query(self, text):
        resp = self.embed_client.embeddings.create(
            model=self.embed_model,
            input=[text],
        )
        return resp.data[0].embedding

    def _build_where_clause(self, where_filter):
        """将 ChromaDB 风格的 dict filter 翻译为 LanceDB SQL where 字符串"""
        if where_filter is None:
            return None
        if '$and' in where_filter:
            parts = [self._build_single_condition(c) for c in where_filter['$and']]
            return ' AND '.join(parts)
        return self._build_single_condition(where_filter)

    def _build_single_condition(self, cond):
        """构建单个 SQL 等值条件"""
        key, value = next(iter(cond.items()))
        escaped = str(value).replace("'", "''")
        return f"{key} = '{escaped}'"

    def _search(self, query_text, where_filter=None, n_results=5):
        embedding = self._embed_query(query_text)

        query = self.table.search(embedding).metric('cosine').limit(n_results)

        where_clause = self._build_where_clause(where_filter)
        if where_clause:
            query = query.where(where_clause, prefilter=True)

        results = query.to_list()

        if not results:
            return json.dumps({"error": "未找到结果"}, ensure_ascii=False, indent=2)

        output = []
        for row in results:
            chunk_type = row.get('type', '')
            distance = row['_distance']

            result_item = {
                'type': chunk_type,
                'distance': round(distance, 3),
                'description': row.get('description', ''),
            }

            # 根据类型添加不同的字段
            if chunk_type == 'class_summary':
                result_item.update({
                    'class_name': row.get('class_name', ''),
                    'method_count': row.get('method_count', ''),
                    'key_methods': row.get('key_methods', ''),
                    'responsibility': row.get('responsibility', ''),
                    'content': row.get('text', ''),
                })
            elif chunk_type == 'module_summary':
                result_item.update({
                    'module_name': row.get('module_name', ''),
                    'file_count': row.get('file_count', ''),
                    'class_count': row.get('class_count', ''),
                    'entry_points': row.get('entry_points', ''),
                    'key_classes': row.get('key_classes', ''),
                    'content': row.get('text', ''),
                })
            else:
                # 函数/方法
                result_item.update({
                    'file': row.get('file', ''),
                    'line': row.get('line', ''),
                    'function': row.get('function', ''),
                    'class': row.get('struct', ''),
                    'module': row.get('module', ''),
                    'action': row.get('action', ''),
                    'code_preview': row.get('text', '')[:800],
                })

            output.append(result_item)

        return json.dumps(output, ensure_ascii=False, indent=2)

    def find_function(self, module="", action="", target="", keyword=""):
        """按模块/动作/对象精确过滤"""
        conditions = []
        if module:
            conditions.append({'module': module})
        if action:
            conditions.append({'action': action})
        if target:
            conditions.append({'target': target})

        where = None
        if len(conditions) > 1:
            where = {'$and': conditions}
        elif conditions:
            where = conditions[0]

        query = keyword or f"{action} {target}"
        return self._search(query, where, n_results=5)

    def find_by_struct(self, struct_name, method_filter=""):
        """按类名过滤"""
        where = {'struct': struct_name}
        query = f"{struct_name} {method_filter}".strip()
        return self._search(query, where, n_results=20)

    def find_by_pattern(self, pattern_type, module=""):
        """
        按代码模式查找。
        patterns 存的是逗号分隔字符串，LanceDB 不支持 LIKE 搜索，
        所以先扩大搜索范围，再在 Python 侧按 patterns 过滤。
        """
        where = None
        if module:
            where = {'module': module}

        # 多搜一些，后面过滤
        results_raw = self._search_raw(pattern_type, where, n_results=30)

        if not results_raw:
            return json.dumps({"error": "未找到结果"}, ensure_ascii=False, indent=2)

        # Python 侧过滤 patterns
        filtered = []
        for item in results_raw:
            patterns = item['_meta'].get('patterns', '')
            if pattern_type in patterns:
                filtered.append(item)

        # 如果过滤后为空，返回原始结果（降级为纯语义匹配）
        if not filtered:
            filtered = results_raw

        # 最多返回10条
        filtered = filtered[:10]

        # 清理内部字段
        for item in filtered:
            item.pop('_meta', None)

        return json.dumps(filtered, ensure_ascii=False, indent=2)

    def find_config(self, name, type_filter=""):
        """查找配置/数据结构"""
        where = None
        if type_filter:
            where = {'type': type_filter}
        return self._search(name, where, n_results=5)

    def find_class_summary(self, class_name):
        """查找类概述"""
        if class_name:
            where = {
                '$and': [
                    {'type': 'class_summary'},
                    {'class_name': class_name}
                ]
            }
        else:
            where = {'type': 'class_summary'}
        return self._search(f"{class_name} 类职责功能", where, n_results=5)

    def find_module_summary(self, module_name):
        """查找模块概述（包含标准流程）"""
        if module_name:
            where = {
                '$and': [
                    {'type': 'module_summary'},
                    {'module_name': module_name}
                ]
            }
        else:
            where = {'type': 'module_summary'}
        return self._search(f"{module_name} 模块流程入口", where, n_results=5)

    def search_by_type(self, query, chunk_type="", n_results=5):
        """按类型搜索（function/class_summary/module_summary）"""
        where = None
        if chunk_type:
            where = {'type': chunk_type}
        return self._search(query, where, n_results=n_results)

    def _search_raw(self, query_text, where_filter=None, n_results=10):
        """搜索并返回带完整元数据的原始结果"""
        embedding = self._embed_query(query_text)

        query = self.table.search(embedding).metric('cosine').limit(n_results)

        where_clause = self._build_where_clause(where_filter)
        if where_clause:
            query = query.where(where_clause, prefilter=True)

        results = query.to_list()

        if not results:
            return []

        output = []
        for row in results:
            output.append({
                'file': row.get('file', ''),
                'line': row.get('line', ''),
                'function': row.get('function', ''),
                'class': row.get('struct', ''),
                'module': row.get('module', ''),
                'action': row.get('action', ''),
                'description': row.get('description', ''),
                'distance': round(row['_distance'], 3),
                'code_preview': row.get('text', '')[:800],
                '_meta': {k: v for k, v in row.items() if k not in ('_distance', 'vector', 'text')},
            })

        return output
