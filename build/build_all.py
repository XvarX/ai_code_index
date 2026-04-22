"""
build_all.py - 一键构建知识库（支持中继）

用法:
  cd build
  python build_all.py          # 从中继点继续（默认）
  python build_all.py --clean  # 从头开始，清除所有缓存
"""

import sys
import os
import time

# 添加 utils 目录到路径
utils_dir = os.path.join(os.path.dirname(__file__), '..', 'utils')
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

from config_helper import load_config

import json
import asyncio

from chunker import chunk_project
from enricher import enrich_all_chunks
from tagger import tag_all_chunks
from describer import describe_all
from class_summarizer import summarize_all_classes
from module_summarizer import summarize_all_modules
from embedder import embed_and_store


def _fmt_elapsed(seconds):
    """格式化耗时"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


# 每一步对应的缓存文件
STEP_FILES = {
    1: 'chunks.json',           # 切块
    2: 'enriched_chunks.json',  # 富化
    3: 'tagged_chunks.json',    # 打标
    4: 'described_chunks.json', # 描述
    5: 'class_summaries.json',  # 类概述
    6: 'module_summaries.json', # 模块概述
    # Step 7 向量化没有中间文件，总是执行
}

# 步骤描述
STEP_NAMES = {
    1: '代码切块',
    2: '上下文富化',
    3: '元数据打标',
    4: 'LLM生成函数/方法描述',
    5: '生成类概述',
    6: '生成模块概述',
    7: '向量化入库',
}


def _find_resume_step(data_dir):
    """找到可以中继的步骤。返回第一个缺少缓存文件的步骤号。"""
    for step in sorted(STEP_FILES.keys()):
        filepath = os.path.join(data_dir, STEP_FILES[step])
        if not os.path.exists(filepath):
            return step

    # 所有中间文件都存在，只需要执行向量化
    return 7


def _load_step(step, data_dir):
    """加载某一步的缓存文件"""
    filename = STEP_FILES.get(step)
    if not filename:
        return None
    filepath = os.path.join(data_dir, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_step(step, data, data_dir):
    """保存某一步的缓存文件"""
    filename = STEP_FILES.get(step)
    if not filename or data is None:
        return
    filepath = os.path.join(data_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main(clean=False):
    total_start = time.time()
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')

    config = load_config(config_path)

    print(f"[OK] 项目根目录: {config['project']['root']}")

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)

    # 确定起始步骤
    if clean:
        start_step = 1
        print("[模式] 从头开始 (--clean)")
    else:
        start_step = _find_resume_step(data_dir)
        if start_step == 1:
            print("[模式] 未找到缓存文件，从头开始")
        else:
            print(f"[模式] 从 Step {start_step} 中继（{STEP_NAMES.get(start_step, '')}）")

    # Step 0: 符号索引由 MCP server 按需构建并缓存

    # Step 1: 切块
    if start_step <= 1:
        print("=" * 50)
        print("Step 1: 代码切块...")
        t = time.time()
        chunks = chunk_project(config)

        # 按类型统计
        type_stats = {}
        for c in chunks:
            type_stats[c['type']] = type_stats.get(c['type'], 0) + 1
        print(f"  -> {len(chunks)} 个代码块 ({', '.join(f'{k}: {v}' for k, v in sorted(type_stats.items()))})")
        print(f"  耗时: {_fmt_elapsed(time.time() - t)}")
        _save_step(1, chunks, data_dir)
    else:
        chunks = _load_step(1, data_dir)
        print(f"[跳过] Step 1: 切块（已有缓存，{len(chunks)} 个代码块）")

    # Step 2: 上下文富化
    if start_step <= 2:
        print("=" * 50)
        print("Step 2: 上下文富化...")
        t = time.time()
        chunks = enrich_all_chunks(chunks)
        print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")
        _save_step(2, chunks, data_dir)
    else:
        chunks = _load_step(2, data_dir)
        print(f"[跳过] Step 2: 富化（已有缓存）")

    # Step 3: 元数据打标
    if start_step <= 3:
        print("=" * 50)
        print("Step 3: 元数据打标...")
        t = time.time()
        chunks = tag_all_chunks(chunks)
        print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")
        _save_step(3, chunks, data_dir)
    else:
        chunks = _load_step(3, data_dir)
        print(f"[跳过] Step 3: 打标（已有缓存）")

    # Step 4: LLM生成函数/方法描述
    if start_step <= 4:
        print("=" * 50)
        print("Step 4: LLM生成函数/方法描述...")
        t = time.time()
        chunks = asyncio.run(describe_all(chunks, config))
        print(f"  -> 完成 {_fmt_elapsed(time.time() - t)}")
        _save_step(4, chunks, data_dir)
    else:
        chunks = _load_step(4, data_dir)
        print(f"[跳过] Step 4: 描述（已有缓存）")

    # Step 5: 生成类概述
    if start_step <= 5:
        print("=" * 50)
        print("Step 5: 生成类概述...")
        t = time.time()
        class_summaries = asyncio.run(summarize_all_classes(chunks, config))
        print(f"  -> {len(class_summaries)} 个类概述 {_fmt_elapsed(time.time() - t)}")
        _save_step(5, class_summaries, data_dir)
    else:
        class_summaries = _load_step(5, data_dir)
        print(f"[跳过] Step 5: 类概述（已有缓存，{len(class_summaries)} 个）")

    # Step 6: 生成模块概述
    if start_step <= 6:
        print("=" * 50)
        print("Step 6: 生成模块概述...")
        t = time.time()
        module_summaries = asyncio.run(summarize_all_modules(chunks, config))
        print(f"  -> {len(module_summaries)} 个模块概述 {_fmt_elapsed(time.time() - t)}")
        _save_step(6, module_summaries, data_dir)
    else:
        module_summaries = _load_step(6, data_dir)
        print(f"[跳过] Step 6: 模块概述（已有缓存，{len(module_summaries)} 个）")

    # Step 7: 合并所有chunk并向量化（总是执行，因为 ChromaDB 需要全量写入）
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
    clean = '--clean' in sys.argv
    main(clean=clean)
