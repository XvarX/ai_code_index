"""
build_all.py - 一键构建知识库（三层架构：函数/类/模块）

用法:
  cd build
  python build_all.py
"""

import sys
import os
import time

# 添加 utils 目录到路径
utils_dir = os.path.join(os.path.dirname(__file__), '..', 'utils')
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

from config_helper import load_config

import yaml
import json
import asyncio

from chunker import chunk_project
from enricher import enrich_all_chunks
from tagger import tag_all_chunks
from describer import describe_all
from class_summarizer import summarize_all_classes
from module_summarizer import summarize_all_modules
from embedder import embed_and_store
from scip_indexer import generate_index, check_scip_available


def _fmt_elapsed(seconds):
    """格式化耗时"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


def main():
    total_start = time.time()
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')

    # 使用新的配置加载函数（支持环境变量和相对路径）
    config = load_config(config_path)

    print(f"[OK] 项目根目录: {config['project']['root']}")

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)

    # Step 0: 生成 SCIP 索引
    print("=" * 50)
    print("Step 0: 生成 SCIP 代码索引...")
    t = time.time()
    scip_available = False
    if check_scip_available():
        try:
            scip_path = os.path.join(data_dir, 'index.scip')
            generate_index(config['project']['root'], scip_path,
                            rag_dirs=config['project'].get('rag_dirs'))
            scip_available = True
        except Exception as e:
            print(f"  SCIP 索引生成失败，将使用简单分析: {e}\n")
    else:
        print("  scip-python 未安装，跳过（npm install -g @sourcegraph/scip-python）\n")
    print(f"  耗时: {_fmt_elapsed(time.time() - t)}")

    # Step 1: 切块
    print("=" * 50)
    print("Step 1: 代码切块...")
    t = time.time()
    chunks = chunk_project(config)
    with open(os.path.join(data_dir, 'chunks.json'), 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    # 按类型统计
    type_stats = {}
    for c in chunks:
        type_stats[c['type']] = type_stats.get(c['type'], 0) + 1
    print(f"  -> {len(chunks)} 个代码块 ({', '.join(f'{k}: {v}' for k, v in sorted(type_stats.items()))})")
    print(f"  耗时: {_fmt_elapsed(time.time() - t)}")

    # Step 2: 上下文富化
    print("=" * 50)
    print("Step 2: 上下文富化...")
    t = time.time()
    chunks = enrich_all_chunks(chunks)
    print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")

    # Step 3: 元数据打标
    print("=" * 50)
    print("Step 3: 元数据打标...")
    t = time.time()
    chunks = tag_all_chunks(chunks)
    print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")

    # Step 4: LLM生成函数/方法描述
    print("=" * 50)
    print("Step 4: LLM生成函数/方法描述...")
    t = time.time()
    chunks = asyncio.run(describe_all(chunks, config))
    print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")

    with open(os.path.join(data_dir, 'described_chunks.json'), 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    # Step 5: 生成类概述
    print("=" * 50)
    print("Step 5: 生成类概述...")
    t = time.time()
    class_summaries = asyncio.run(summarize_all_classes(chunks, config))
    with open(os.path.join(data_dir, 'class_summaries.json'), 'w', encoding='utf-8') as f:
        json.dump(class_summaries, f, ensure_ascii=False, indent=2)
    print(f"  -> {len(class_summaries)} 个类概述 {_fmt_elapsed(time.time() - t)}")

    # Step 6: 生成模块概述
    print("=" * 50)
    print("Step 6: 生成模块概述（使用 SCIP 分析调用关系）...")
    t = time.time()
    module_summaries = asyncio.run(summarize_all_modules(chunks, config, use_scip=scip_available))
    with open(os.path.join(data_dir, 'module_summaries.json'), 'w', encoding='utf-8') as f:
        json.dump(module_summaries, f, ensure_ascii=False, indent=2)
    print(f"  -> {len(module_summaries)} 个模块概述 {_fmt_elapsed(time.time() - t)}")

    # Step 7: 合并所有chunk并向量化
    print("=" * 50)
    print("Step 7: 向量化入库（函数 + 类 + 模块）...")
    t = time.time()
    all_chunks = chunks + class_summaries + module_summaries
    embed_and_store(all_chunks, config)
    print(f"  耗时: {_fmt_elapsed(time.time() - t)}")

    print("=" * 50)
    print("知识库构建完成！")
    print(f"总耗时: {_fmt_elapsed(time.time() - total_start)}")
    print(f"数据库位置: {os.path.join(data_dir, 'chroma_db')}")
    print(f"总计: {len(chunks)} 个函数, {len(class_summaries)} 个类, {len(module_summaries)} 个模块")


if __name__ == '__main__':
    main()
