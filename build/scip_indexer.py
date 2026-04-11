"""
scip_indexer.py - SCIP 索引生成器
构建步骤: 运行 scip-python 生成 index.scip
"""

import subprocess
import os
import sys
import shutil


def _patch_windows_sep_bug():
    """
    修复 scip-python 在 Windows 上的 path.sep 正则 bug
    https://github.com/sourcegraph/scip-python/issues/211
    RegExp(o.sep,"g") 在 Windows 上因 path.sep=反斜杠 导致崩溃

    策略：首次运行时备份原始文件，后续如果 patch 出问题就从备份恢复。
    完全离线可用，不需要重新安装。
    """
    scip_exe = shutil.which('scip-python')
    if not scip_exe:
        return False

    scip_js = os.path.join(
        os.path.dirname(scip_exe),
        'node_modules', '@sourcegraph', 'scip-python',
        'dist', 'scip-python.js'
    )
    scip_js = os.path.normpath(scip_js)

    if not os.path.exists(scip_js):
        return False

    backup_path = scip_js + '.orig'

    # 首次运行：备份原始文件（还没被 patch 过的）
    if not os.path.exists(backup_path):
        shutil.copy2(scip_js, backup_path)

    with open(scip_js, 'r', encoding='utf-8') as f:
        content = f.read()

    original = 'RegExp(o.sep,"g")'
    correct = r'RegExp(o.sep.replace(/\\/g,"\\\\"),"g")'

    # 已经是正确的 patch，跳过
    if correct in content:
        return False

    # 文件不在已知状态 → 从备份恢复原始文件
    if original not in content:
        shutil.copy2(backup_path, scip_js)
        with open(scip_js, 'r', encoding='utf-8') as f:
            content = f.read()
        print("  [SCIP] Restored scip-python.js from backup")

    # 应用 patch
    if original in content:
        content = content.replace(original, correct)
        with open(scip_js, 'w', encoding='utf-8') as f:
            f.write(content)
        print("  [SCIP] Fixed Windows path.sep bug")
        return True

    return False


def check_scip_available() -> bool:
    """检查 scip-python 是否可用"""
    return shutil.which('scip-python') is not None


def generate_index(project_root: str, output_path: str) -> str:
    """
    运行 scip-python 生成 SCIP 索引

    Args:
        project_root: 要索引的项目目录（绝对路径）
        output_path: 输出的 index.scip 路径

    Returns:
        生成的 index.scip 文件路径
    """
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Windows: 自动修复 scip-python 的 path.sep bug
    if sys.platform == 'win32':
        _patch_windows_sep_bug()

    # Windows 上 subprocess 可能找不到 .cmd 文件，使用完整路径
    scip_exe = shutil.which('scip-python')
    cmd = [
        scip_exe, 'index', project_root,
        '--project-name', os.path.basename(project_root),
        '--output', output_path,
    ]

    print(f"  [SCIP] 生成索引: {project_root}")

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=300,
        shell=(sys.platform == 'win32'),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"scip-python 失败 (exit {result.returncode}):\n"
            f"{result.stderr[:500]}"
        )

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"索引文件未生成: {output_path}")

    size_kb = os.path.getsize(output_path) / 1024
    print(f"  [SCIP] 索引生成完成: {output_path} ({size_kb:.1f} KB)")
    return output_path


if __name__ == '__main__':
    utils_dir = os.path.join(os.path.dirname(__file__), '..', 'utils')
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)
    from config_helper import load_config

    config = load_config(os.path.join(os.path.dirname(__file__), '..', 'config.yaml'))
    project_root = config['project']['root']
    output_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'index.scip')

    generate_index(project_root, output_path)
