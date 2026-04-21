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


def _ensure_git_repo(project_root: str) -> bool:
    """
    确保项目目录是 Git 仓库，如果不是则自动初始化
    返回 True 如果已经初始化或成功初始化
    """
    git_dir = os.path.join(project_root, '.git')
    if os.path.exists(git_dir):
        return True  # 已经是 Git 仓库

    print(f"  [SCIP] 项目不是 Git 仓库，自动初始化...")
    try:
        import subprocess
        subprocess.run(
            ['git', 'init'],
            cwd=project_root,
            capture_output=True,
            check=True,
            shell=(sys.platform == 'win32')
        )
        subprocess.run(
            ['git', 'add', '.'],
            cwd=project_root,
            capture_output=True,
            check=True,
            shell=(sys.platform == 'win32')
        )
        subprocess.run(
            ['git', 'commit', '-m', 'Initial commit for SCIP'],
            cwd=project_root,
            capture_output=True,
            check=True,
            shell=(sys.platform == 'win32')
        )
        print(f"  [SCIP] Git 仓库初始化完成")
        return True
    except Exception as e:
        print(f"  [SCIP] Git 初始化失败: {e}")
        return False


def _run_scip_on_dir(scan_dir: str, output_path: str, scip_exe: str):
    """对单个目录运行 scip-python 生成索引"""
    cmd = [
        scip_exe, 'index', scan_dir,
        '--project-name', os.path.basename(scan_dir),
        '--output', output_path,
    ]

    print(f"  [SCIP] 生成索引: {scan_dir}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=scan_dir,
        shell=(sys.platform == 'win32'),
    )

    for line in proc.stdout:
        print(f"  [SCIP] {line.rstrip()}")

    _, stderr = proc.communicate(timeout=300)
    returncode = proc.returncode

    if returncode != 0:
        stderr_lower = stderr.lower()
        if 'not a git repository' in stderr_lower or 'git' in stderr_lower:
            raise RuntimeError(
                f"scip-python 需要 Git 仓库，但 {scan_dir} 不是 Git 仓库。\n"
                f"请在项目目录初始化 Git 仓库。"
            )
        else:
            raise RuntimeError(
                f"scip-python 失败 (exit {returncode}):\n"
                f"{stderr[:500]}"
            )

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"索引文件未生成: {output_path}")


def _merge_scip_files(partial_pairs: list, output_path: str):
    """合并多个 .scip 文件为一个，修正路径为相对 project_root。

    Args:
        partial_pairs: [(scip_path, rag_dir), ...] rag_dir 用于补全路径前缀
        output_path: 合并后的输出路径
    """
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, os.path.join(_dir, '..', 'mcp_server'))
    from scip_pb2 import Index as ScipIndexProto

    merged = ScipIndexProto()
    for scip_path, rag_dir in partial_pairs:
        prefix = rag_dir.replace('\\', '/').strip('/') + '/'
        partial = ScipIndexProto()
        with open(scip_path, 'rb') as f:
            partial.ParseFromString(f.read())
        for doc in partial.documents:
            raw = doc.relative_path.replace('\\', '/')
            # 如果路径不以 rag_dir 开头，说明 scip-python 用了子目录作为基准，需要补前缀
            if not raw.startswith(prefix.rstrip('/')):
                doc.relative_path = prefix + raw
            merged.documents.append(doc)
        for sym in partial.external_symbols:
            merged.external_symbols.append(sym)

    with open(output_path, 'wb') as f:
        f.write(merged.SerializeToString())


def generate_index(project_root: str, output_path: str, rag_dirs=None) -> str:
    """
    运行 scip-python 生成 SCIP 索引

    Args:
        project_root: 项目根目录（绝对路径）
        output_path: 输出的 index.scip 路径
        rag_dirs: 可选，只索引这些子目录（相对 project_root）

    Returns:
        生成的 index.scip 文件路径
    """
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    # 自动初始化 Git 仓库（如果需要）
    if not _ensure_git_repo(project_root):
        raise RuntimeError(
            f"无法初始化 Git 仓库: {project_root}\n"
            f"SCIP 需要项目是 Git 仓库。请手动执行：\n"
            f"  cd {project_root}\n"
            f"  git init\n"
            f"  git add .\n"
            f"  git commit -m 'Initial commit'"
        )

    # Windows: 自动修复 scip-python 的 path.sep bug
    if sys.platform == 'win32':
        _patch_windows_sep_bug()

    scip_exe = shutil.which('scip-python')

    if rag_dirs:
        # 按每个 rag_dir 分别生成，再合并
        partial_pairs = []  # [(path, rag_dir), ...]
        for rag_dir in rag_dirs:
            scan_dir = os.path.join(project_root, rag_dir)
            if not os.path.isdir(scan_dir):
                print(f"  警告: rag_dirs 中的目录不存在: {scan_dir}")
                continue
            partial_path = output_path + f'.{rag_dir.replace("/", "_").replace(os.sep, "_")}'
            _run_scip_on_dir(scan_dir, partial_path, scip_exe)
            partial_pairs.append((partial_path, rag_dir))

        if not partial_pairs:
            raise FileNotFoundError("rag_dirs 中没有有效目录，无法生成索引")

        # 合并并修正路径（单目录也需要修正路径前缀）
        _merge_scip_files(partial_pairs, output_path)
        # 清理临时文件
        for p, _ in partial_pairs:
            if os.path.exists(p):
                os.remove(p)
    else:
        # 全量索引
        _run_scip_on_dir(project_root, output_path, scip_exe)

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

    generate_index(project_root, output_path, rag_dirs=config['project'].get('rag_dirs'))
