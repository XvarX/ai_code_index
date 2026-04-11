import yaml
from chunker import chunk_project
from module_summarizer import _group_chunks_by_module

config = yaml.safe_load(open('../config.yaml', encoding='utf-8'))
chunks = chunk_project(config)
modules = _group_chunks_by_module(chunks, config)

print('详细文件分布:')
for name, g in sorted(modules.items()):
    print(f'\n模块: {name}')
    for f in sorted(g['files']):
        print(f'  - {f}')
