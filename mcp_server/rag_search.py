"""
rag_search.py - RAG查询实现
结构化查询 + 语义搜索
支持两种 embedding 模式: api (远程向量模型) / local (ChromaDB 内置)
"""

import json
import os
import chromadb


class RAGSearcher:
    def __init__(self, config):
        self.project_root = config.get('project', {}).get('root', '')
        db_path = config.get('db_path', '')
        if not os.path.isabs(db_path):
            here = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.normpath(os.path.join(here, '..', 'data', 'chroma_db'))
        self.db_client = chromadb.PersistentClient(path=db_path)
        self.collection = self.db_client.get_or_create_collection(
            name="game_server_code",
            metadata={"hnsw:space": "cosine"},
        )

        self.mode = config.get('embedding', {}).get('mode', 'api')

        if self.mode == 'api':
            from openai import OpenAI
            self.embed_client = OpenAI(
                api_key=config['embedding'].get('api_key') or os.getenv('OPENAI_API_KEY'),
                base_url=config['embedding']['base_url'],
            )
            self.embed_model = config['embedding']['model']
        else:
            self.embed_client = None
            self.embed_model = None

    def _normalize_file_path(self, file_path):
        """归一化文件路径，兼容不同 OS 构建的数据。

        处理场景：
        - Linux 绝对路径: /home/user/project/testhd/gameplay/box.py
        - 相对路径（正斜杠）: gameplay/box.py 或 testhd/gameplay/box.py
        - Windows 绝对路径: d:\\space\\...\\testhd\\gameplay\\box.py
        """
        if not file_path:
            return file_path

        project_root = self.project_root
        if not project_root:
            return file_path.replace('/', os.sep)

        norm_file = file_path.replace('\\', '/')
        norm_root = project_root.replace('\\', '/').rstrip('/')
        project_name = os.path.basename(norm_root)

        # 已经是当前项目根目录下的路径，直接修正分隔符
        if norm_file.startswith(norm_root + '/'):
            return os.path.normpath(file_path)

        # 以项目名开头的相对路径: testhd/gameplay/box.py -> gameplay/box.py
        prefix = project_name + '/'
        if project_name and norm_file.startswith(prefix):
            rel_part = norm_file[len(prefix):]
            return os.path.normpath(os.path.join(project_root, rel_part))

        # 绝对路径中包含项目名: /home/user/testhd/gameplay/box.py -> gameplay/box.py
        marker = '/' + project_name + '/'
        if project_name and marker in norm_file:
            idx = norm_file.find(marker)
            rel_part = norm_file[idx + len(marker):]
            return os.path.normpath(os.path.join(project_root, rel_part))

        # 普通相对路径: gameplay/box.py
        if not os.path.isabs(file_path):
            return os.path.normpath(os.path.join(project_root, norm_file))

        # 兜底：修正分隔符
        return os.path.normpath(file_path)

    def _embed_query(self, text):
        """向量化查询文本（仅 api 模式）"""
        resp = self.embed_client.embeddings.create(
            model=self.embed_model,
            input=[text],
        )
        return resp.data[0].embedding

    def _search(self, query_text, where_filter=None, n_results=5):
        kwargs = {
            "n_results": n_results,
        }
        if where_filter:
            kwargs["where"] = where_filter

        if self.mode == 'local':
            kwargs["query_texts"] = [query_text]
        else:
            embedding = self._embed_query(query_text)
            kwargs["query_embeddings"] = [embedding]

        results = self.collection.query(**kwargs)

        if not results["ids"][0]:
            return json.dumps({"error": "未找到结果"}, ensure_ascii=False)

        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            chunk_type = meta.get('type', '')

            result_item = {
                'type': chunk_type,
                'distance': round(distance, 3),
                'description': meta.get('description', ''),
            }

            if chunk_type == 'class_summary':
                result_item.update({
                    'class_name': meta.get('class_name', ''),
                    'key_methods': meta.get('key_methods', ''),
                    'responsibility': meta.get('responsibility', ''),
                })
            elif chunk_type == 'module_summary':
                result_item.update({
                    'module_name': meta.get('module_name', ''),
                    'entry_points': meta.get('entry_points', ''),
                    'key_classes': meta.get('key_classes', ''),
                })
            else:
                result_item.update({
                    'file': self._normalize_file_path(meta.get('file', '')),
                    'line': meta.get('line', ''),
                    'function': meta.get('function', ''),
                    'class': meta.get('struct', ''),
                })

            output.append(result_item)

        return json.dumps(output, ensure_ascii=False)

    def _search_raw(self, query_text, where_filter=None, n_results=10):
        """搜索并返回带完整元数据的原始结果"""
        kwargs = {
            "n_results": n_results,
        }
        if where_filter:
            kwargs["where"] = where_filter

        if self.mode == 'local':
            kwargs["query_texts"] = [query_text]
        else:
            embedding = self._embed_query(query_text)
            kwargs["query_embeddings"] = [embedding]

        results = self.collection.query(**kwargs)

        if not results["ids"][0]:
            return []

        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            output.append({
                'file': self._normalize_file_path(meta.get('file', '')),
                'line': meta.get('line', ''),
                'function': meta.get('function', ''),
                'class': meta.get('struct', ''),
                'description': meta.get('description', ''),
                'distance': round(distance, 3),
                '_meta': dict(meta),
            })

        return output

    def find_function(self, module="", action="", target="", keyword=""):
        """向后兼容：映射到 search_by_type"""
        query = keyword or f"{action} {target}"
        return self.search_by_type(query, module=module, action=action, target=target)

    def find_by_struct(self, struct_name, method_filter=""):
        """按类名过滤"""
        where = {'struct': struct_name}
        query = f"{struct_name} {method_filter}".strip()
        return self._search(query, where, n_results=5)

    def find_by_pattern(self, pattern_type, module=""):
        """
        按代码模式查找。
        patterns 存的是逗号分隔字符串，ChromaDB 不支持 LIKE 搜索，
        所以先扩大搜索范围，再在 Python 侧按 patterns 过滤。
        """
        where = None
        if module:
            where = {'module': module}

        results_raw = self._search_raw(pattern_type, where, n_results=30)

        if not results_raw:
            return json.dumps({"error": "未找到结果"}, ensure_ascii=False)

        filtered = []
        for item in results_raw:
            patterns = item['_meta'].get('patterns', '')
            if pattern_type in patterns:
                filtered.append(item)

        if not filtered:
            filtered = results_raw

        filtered = filtered[:5]

        for item in filtered:
            item.pop('_meta', None)

        return json.dumps(filtered, ensure_ascii=False)

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
        result = self._search(f"{module_name} 模块流程入口", where, n_results=5)

        # 精确匹配无结果时，回退到仅按类型+语义搜索（支持短模块名如 "monster"）
        if module_name and '"error": "未找到结果"' in result:
            fallback_where = {'type': 'module_summary'}
            result = self._search(f"{module_name} 模块流程入口", fallback_where, n_results=5)

        return result

    def search_by_type(self, query, chunk_type="", module="", action="", target="", n_results=5):
        """按类型搜索（function/class_summary/module_summary），支持精确过滤"""
        conditions = []
        if chunk_type:
            conditions.append({'type': chunk_type})
        if module:
            conditions.append({'module': module})
        if action:
            conditions.append({'action': action})
        if target:
            conditions.append({'target': target})
        if len(conditions) > 1:
            where = {'$and': conditions}
        elif conditions:
            where = conditions[0]
        else:
            where = None
        return self._search(query, where, n_results=n_results)
