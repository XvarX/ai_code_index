"""
配置文件加载辅助函数
支持环境变量和相对路径解析
"""
import os
import re
import yaml


def expand_env_vars(text):
    """
    展开环境变量
    支持 ${VAR:-default} 语法

    示例：
        "${GAME_SERVER_ROOT:-./testhd}" -> "/actual/path" 或 "./testhd"
    """
    if not isinstance(text, str):
        return text

    # 匹配 ${VAR:-default} 格式
    pattern = r'\$\{([^:}]+):-([^}]+)\}'

    def replace_env_var(match):
        var_name = match.group(1)
        default_value = match.group(2)
        return os.environ.get(var_name, default_value)

    return re.sub(pattern, replace_env_var, text)


def resolve_path(config_path, path_str):
    """
    解析路径（支持相对路径和绝对路径）

    Args:
        config_path: 配置文件的绝对路径
        path_str: 配置中的路径字符串

    Returns:
        解析后的绝对路径
    """
    # 先展开环境变量
    expanded = expand_env_vars(path_str)

    # 如果是绝对路径，直接返回
    if os.path.isabs(expanded):
        return expanded

    # 相对路径：相对于配置文件所在目录
    config_dir = os.path.dirname(config_path)
    return os.path.abspath(os.path.join(config_dir, expanded))


def load_config(config_path):
    """
    加载配置文件并处理环境变量和路径

    Args:
        config_path: 配置文件路径

    Returns:
        处理后的配置字典
    """
    config_path = os.path.abspath(config_path)

    with open(config_path, encoding='utf-8') as f:
        config_text = f.read()

    # 展开环境变量
    config_text = expand_env_vars(config_text)

    # 解析 YAML
    config = yaml.safe_load(config_text)

    # 处理路径字段
    if 'project' in config and 'root' in config['project']:
        config['project']['root'] = resolve_path(
            config_path,
            config['project']['root']
        )

    return config


if __name__ == "__main__":
    # 测试
    config = load_config("../config.yaml")
    print("Project root:", config['project']['root'])
