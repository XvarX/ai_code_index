"""
update.py - 增量更新知识库
检测git变更，只重新处理修改过的文件

用法:
  cd build
  python update.py              # 默认对比 HEAD~1
  python update.py HEAD~5       # 对比最近5个commit
"""

import subprocess
import os
import json
import asyncio
import sys

from chunker import extract_chunks
from enricher import enrich_all_chunks
from tagger import tag_all_chunks
from describer import describe_all
from embedder import embed_and_store, get_collection


def get_changed_files(since_commit='HEAD~1'):
    result = subprocess.run(
        ['git', 'diff', '--name-only', since_commit],
        capture_output=True, text=True,
    )
    files = result.stdout.strip().split('\n')
    return [f for f in files if f.endswith('.py') and f.strip()]


def incremental_update(changed_files, config):
    collection = get_collection(config)

    # 1. 删除旧chunk
    for filepath in changed_files:
        try:
            escaped = filepath.replace("'", "''")
            collection.delete(f"file = '{escaped}'")
            print(f"  删除旧数据: {filepath}")
        except Exception:
            pass

    # 2. 重新处理变更文件
    all_chunks = []
    for filepath in changed_files:
        full_path = os.path.join(config['project']['root'], filepath)
        if os.path.exists(full_path):
            chunks = extract_chunks(full_path)
            all_chunks.extend(chunks)

    if not all_chunks:
        print("没有需要更新的代码块")
        return

    # 3. 完整流程
    enriched = enrich_all_chunks(all_chunks)
    tagged = tag_all_chunks(enriched)
    described = asyncio.run(describe_all(tagged, config))
    embed_and_store(described, config)

    print(f"增量更新完成: {len(described)} 个代码块")


if __name__ == '__main__':
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    since = sys.argv[1] if len(sys.argv) > 1 else 'HEAD~1'
    changed = get_changed_files(since)
    print(f"检测到 {len(changed)} 个Python文件变更")
    if changed:
        incremental_update(changed, config)
