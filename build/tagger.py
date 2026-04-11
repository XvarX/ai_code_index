"""
tagger.py - 自动元数据打标
从代码的路径、命名中推断结构化标签
"""

import os

# 根据你的项目结构调整这些列表
KNOWN_MODULES = {
    'scene', 'activity', 'reward', 'player', 'npc', 'monster',
    'item', 'shop', 'mail', 'guild', 'team', 'chat', 'friend',
    'dungeon', 'boss', 'arena', 'rank', 'quest', 'task',
    'login', 'fight', 'battle', 'map', 'config', 'network',
    'protocol', 'handler', 'manager', 'service', 'model',
    'skill', 'buff', 'pet', 'mount', 'wing', 'artifact',
    'daily', 'weekly', 'monthly', 'season', 'event',
}

ACTION_PREFIXES = {
    'create': ['create_', 'new_', 'add_', 'spawn_', 'gen_'],
    'delete': ['delete_', 'remove_', 'destroy_', 'del_', 'clear_'],
    'update': ['update_', 'modify_', 'set_', 'change_', 'refresh_'],
    'query':  ['get_', 'find_', 'query_', 'search_', 'fetch_', 'load_', 'read_'],
    'save':   ['save_', 'store_', 'write_', 'persist_', 'dump_'],
    'handle': ['handle_', 'on_', 'process_', 'dispatch_', 'deal_with_'],
    'check':  ['check_', 'validate_', 'verify_', 'can_', 'is_', 'has_'],
    'init':   ['init_', 'setup_', 'initialize_', 'register_'],
    'start':  ['start_', 'begin_', 'enter_', 'launch_'],
    'stop':   ['stop_', 'end_', 'finish_', 'exit_', 'close_', 'cleanup_'],
    'send':   ['send_', 'notify_', 'broadcast_', 'push_', 'emit_'],
    'calc':   ['calc_', 'compute_', 'evaluate_', 'resolve_'],
}

CODE_PATTERNS = {
    '创建流程': ['create', 'new', 'spawn', 'init', 'setup'],
    '事件处理': ['handle', 'on_', 'event', 'listener', 'callback'],
    '定时任务': ['cron', 'schedule', 'timer', 'periodic', 'daily', 'tick'],
    '协议处理': ['handler', 'request', 'response', 'msg', 'packet'],
    '数据持久化': ['save', 'load', 'db', 'cache', 'redis', 'mongo'],
    '状态机': ['state', 'enter', 'exit', 'transition'],
    '奖励发放': ['reward', 'give', 'award', 'loot', 'drop'],
    '匹配/组队': ['match', 'team', 'group', 'party'],
}


def infer_module(filepath):
    parts = filepath.replace('\\', '/').split('/')
    for part in parts:
        lower = part.lower().replace('-', '_')
        if lower in KNOWN_MODULES:
            return lower
        if lower.rstrip('s') in KNOWN_MODULES:
            return lower.rstrip('s')
    if len(parts) >= 2:
        return parts[-2].lower()
    return 'unknown'


def infer_action(func_name):
    lower = func_name.lower()
    for action, prefixes in ACTION_PREFIXES.items():
        for prefix in prefixes:
            if lower.startswith(prefix):
                return action
    return 'other'


def infer_target(func_name):
    lower = func_name.lower()
    for action, prefixes in ACTION_PREFIXES.items():
        for prefix in prefixes:
            if lower.startswith(prefix):
                target = lower[len(prefix):]
                if target:
                    return target.rstrip('_')
    return lower


def infer_pattern(func_name, code):
    combined = (func_name + ' ' + code[:500]).lower()
    matched = []
    for pattern, keywords in CODE_PATTERNS.items():
        for kw in keywords:
            if kw in combined:
                matched.append(pattern)
                break
    return matched


def tag_chunk(chunk):
    filepath = chunk['file']
    func_name = chunk['name']
    code = chunk.get('code', '')
    return {
        'module': infer_module(filepath),
        'action': infer_action(func_name),
        'target': infer_target(func_name),
        'patterns': infer_pattern(func_name, code),
        'struct': chunk.get('class_name') or '',
        'function': func_name,
        'file': filepath,
        'line': chunk['start_line'],
    }


def tag_all_chunks(chunks):
    for chunk in chunks:
        chunk['tags'] = tag_chunk(chunk)
    return chunks


if __name__ == '__main__':
    import json
    with open('../data/enriched_chunks.json', 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    tagged = tag_all_chunks(chunks)
    with open('../data/tagged_chunks.json', 'w', encoding='utf-8') as f:
        json.dump(tagged, f, ensure_ascii=False, indent=2)
    print(f"打标完成: {len(tagged)} 个代码块")
