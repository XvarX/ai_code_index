"""
build_all.py - 一键构建知识库（三层架构：函数/类/模块）

用法:
  cd build
  python build_all.py
"""

import sys
import os

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


def main():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')

    # 使用新的配置加载函数（支持环境变量和相对路径）
    config = load_config(config_path)

    print(f"[OK] 项目根目录: {config['project']['root']}")

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)

    # Step 0: 生成 SCIP 索引
    print("=" * 50)
    print("Step 0: 生成 SCIP 代码索引...")
    scip_available = False
    if check_scip_available():
        try:
            scip_path = os.path.join(data_dir, 'index.scip')
            generate_index(config['project']['root'], scip_path)
            scip_available = True
        except Exception as e:
            print(f"  SCIP 索引生成失败，将使用简单分析: {e}\n")
    else:
        print("  scip-python 未安装，跳过（npm install -g @sourcegraph/scip-python）\n")

    # Step 1: 切块
    print("=" * 50)
    print("Step 1: 代码切块...")
    chunks = chunk_project(config)
    with open(os.path.join(data_dir, 'chunks.json'), 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"  -> {len(chunks)} 个代码块\n")

    # Step 2: 上下文富化
    print("Step 2: 上下文富化...")
    chunks = enrich_all_chunks(chunks)
    print(f"  -> 完成\n")

    # Step 3: 元数据打标
    print("Step 3: 元数据打标...")
    chunks = tag_all_chunks(chunks)
    print(f"  -> 完成\n")

    # Step 4: LLM生成函数/方法描述
    print("Step 4: LLM生成函数/方法描述...")
    chunks = asyncio.run(describe_all(chunks, config))
    print(f"  -> 完成\n")

    with open(os.path.join(data_dir, 'described_chunks.json'), 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    # Step 5: 生成类概述
    print("Step 5: 生成类概述...")
    class_summaries = asyncio.run(summarize_all_classes(chunks, config))
    with open(os.path.join(data_dir, 'class_summaries.json'), 'w', encoding='utf-8') as f:
        json.dump(class_summaries, f, ensure_ascii=False, indent=2)
    print(f"  -> {len(class_summaries)} 个类概述\n")

    # Step 6: 生成模块概述
    print("Step 6: 生成模块概述（使用 SCIP 分析调用关系）...")
    module_summaries = asyncio.run(summarize_all_modules(chunks, config, use_scip=scip_available))
    with open(os.path.join(data_dir, 'module_summaries.json'), 'w', encoding='utf-8') as f:
        json.dump(module_summaries, f, ensure_ascii=False, indent=2)
    print(f"  -> {len(module_summaries)} 个模块概述\n")

    # Step 7: 合并所有chunk并向量化
    print("Step 7: 向量化入库（函数 + 类 + 模块）...")
    all_chunks = chunks + class_summaries + module_summaries
    embed_and_store(all_chunks, config)

    print("=" * 50)
    print("知识库构建完成！")
    print(f"数据库位置: {os.path.join(data_dir, 'chroma_db')}")
    print(f"总计: {len(chunks)} 个函数, {len(class_summaries)} 个类, {len(module_summaries)} 个模块")


if __name__ == '__main__':
    main()
