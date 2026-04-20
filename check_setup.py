#!/usr/bin/env python3
"""
快速诊断脚本 - 检查项目配置是否正确
"""
import os
import sys

def check_file_exists(filepath, description):
    """检查文件是否存在"""
    exists = os.path.exists(filepath)
    status = "[OK]" if exists else "[FAIL]"
    print(f"{status} {description}: {filepath}")
    return exists

def check_module_import(module_name, description):
    """检查模块是否可导入"""
    try:
        __import__(module_name)
        print(f"[OK] {description}: {module_name}")
        return True
    except ImportError:
        print(f"[FAIL] {description}: {module_name} (未安装)")
        return False

def main():
    print("="*60)
    print("项目配置诊断")
    print("="*60)

    # 检查文件结构
    print("\n【文件结构检查】")
    checks = [
        ("config.yaml", "配置文件"),
        ("build/build_all.py", "构建脚本"),
        ("mcp_server/server.py", "MCP 服务器"),
        ("mcp_server/mcp_agent_simulator.py", "MCP 模拟器"),
        ("utils/config_helper.py", "配置辅助函数"),
        ("testhd", "项目代码目录"),
        ("data/chroma_db", "向量数据库"),
    ]

    all_files_exist = True
    for filepath, desc in checks:
        if not check_file_exists(filepath, desc):
            all_files_exist = False

    # 检查 Python 模块
    print("\n【Python 模块检查】")
    modules = [
        ("yaml", "PyYAML"),
        ("chromadb", "ChromaDB"),
        ("mcp", "MCP SDK"),
        ("lsp_client", "LSP 客户端"),
    ]

    all_modules_exist = True
    for module, desc in modules:
        if not check_module_import(module, desc):
            all_modules_exist = False

    # 检查配置
    print("\n【配置检查】")
    try:
        sys.path.insert(0, 'utils')
        from config_helper import load_config
        config = load_config("config.yaml")
        root = config['project']['root']

        if os.path.exists(root):
            print(f"[OK] 项目根目录存在: {root}")
        else:
            print(f"[FAIL] 项目根目录不存在: {root}")
            print(f"   提示：请检查 config.yaml 中的 root 配置")
            all_files_exist = False

    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        all_files_exist = False

    # 诊断结果
    print("\n" + "="*60)
    if all_files_exist and all_modules_exist:
        print("[OK] 所有检查通过！项目配置正确。")
        print("\n下一步：")
        print("  1. 如果数据库不存在，运行: cd build && python build_all.py")
        print("  2. 启动 MCP 服务器: cd mcp_server && python server.py")
        print("  3. 测试查询: python mcp_agent_simulator.py")
    else:
        print("[FAIL] 发现问题，请按照上述提示修复。")

        if not all_modules_exist:
            print("\n安装缺失的依赖:")
            print("  pip install -r requirements.txt")

        if not all_files_exist:
            print("\n缺失文件或目录，请检查项目结构。")

    print("="*60)

if __name__ == "__main__":
    main()
