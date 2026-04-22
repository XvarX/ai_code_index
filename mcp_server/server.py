"""
server.py - MCP Server 主程序（使用标准 MCP SDK）
暴露结构化查询工具，供Claude Agent调用

启动方式:
  cd mcp_server
  python server.py
"""

import sys
import os
import json
import logging
from datetime import datetime
import asyncio

# ===== 配置日志 =====
log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, f"mcp_server_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# 配置日志格式（只输出到文件和 stderr，不干扰 stdout）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stderr)
    ]
)

logger = logging.getLogger(__name__)

# ===== 导入模块 =====
# 添加 utils 目录到路径
utils_dir = os.path.join(os.path.dirname(__file__), '..', 'utils')
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

from config_helper import load_config

try:
    from mcp.server.models import InitializationOptions
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    logger.info("✓ MCP SDK 导入成功")
except ImportError as e:
    logger.error(f"✗ MCP SDK 导入失败: {e}")
    logger.error("  请安装: pip install mcp")
    sys.exit(1)

try:
    from rag_search import RAGSearcher
    logger.info("✓ RAG 搜索模块导入成功")
except Exception as e:
    logger.error(f"✗ RAG 搜索模块导入失败: {e}")
    sys.exit(1)

try:
    from lsp_client import LSPClient
    logger.info("✓ LSP 客户端模块导入成功")
except Exception as e:
    logger.error(f"✗ LSP 客户端模块导入失败: {e}")
    sys.exit(1)

# ===== 加载配置 =====
logger.info("="*60)
logger.info("MCP 服务器启动中...")
logger.info("="*60)

config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
logger.info(f"配置文件路径: {config_path}")

try:
    config = load_config(config_path)
    logger.info(f"✓ 配置加载成功")
    logger.info(f"  项目根目录: {config['project']['root']}")
    logger.info(f"  项目语言: {config['project'].get('language', 'python')}")
except Exception as e:
    logger.error(f"✗ 配置加载失败: {e}")
    logger.error(f"  配置文件: {config_path}")
    sys.exit(1)

# ===== 初始化组件 =====
logger.info("初始化 RAG 搜索器...")
try:
    rag = RAGSearcher(config)
    logger.info("✓ RAG 搜索器初始化成功")
except Exception as e:
    logger.error(f"✗ RAG 搜索器初始化失败: {e}")
    import traceback
    logger.error(traceback.format_exc())
    sys.exit(1)

# 初始化 LSP 客户端（懒启动，首次查询时才真正连接）
lsp_config = config.get('lsp', {})
lsp = LSPClient(config['project']['root'], lsp_config)
import atexit
atexit.register(lsp.shutdown)
logger.info("✓ LSP 客户端已创建（将在首次查询时启动 pyright）")

# 启动时预构建符号索引（供 search_function / find_inheritance 使用）
logger.info("正在构建符号索引...")
lsp._build_symbol_index()
count = len(lsp._symbol_index) if lsp._symbol_index else 0
logger.info(f"✓ 符号索引就绪: {count} 个符号")

# ===== 创建 MCP 服务器 =====
server = Server("game_server_rag")

logger.info(f"日志文件: {log_file}")
logger.info("="*60)
logger.info("MCP 服务器已就绪，等待请求...")
logger.info("="*60)


# ===== 工具定义 =====

def create_tool(name: str, description: str, parameters: dict) -> Tool:
    """创建工具定义"""
    return Tool(
        name=name,
        description=description,
        inputSchema=parameters
    )


# ===== 列出工具 =====

@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        # 第一层：符号搜索（精确、零 API 调用）
        create_tool(
            "search_function",
            "按代码标识符名称搜索符号定义（类名/函数名/方法名）。只接受英文标识符，如 MonsterManager、spawn_monster、MonsterManager.spawn_monster。不支持中文搜索。如果要用中文或自然语言查询（如'怪物管理'、'副本奖励'），请改用 search_by_type。重要：参数必须来自 Read 代码时看到的实际标识符，或本工具链其他工具返回的结果，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "英文符号名，必须从代码中获取。支持: 类名(MonsterManager)、类.方法(MonsterManager.spawn_monster)、纯方法名(spawn_monster)。不支持中文，禁止猜测。"},
                    "kind": {"type": "string", "description": "类型过滤: class/method/function", "default": ""}
                }
            }
        ),
        create_tool(
            "list_symbols",
            "[备用] 列出文件中所有类和方法定义。大多数场景直接 Read 文件即可。仅用于超大文件的结构速览。参数必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "文件相对路径，必须从代码或工具返回中获取，禁止猜测"},
                    "kind": {"type": "string", "description": "类型过滤: class/method/function", "default": ""}
                }
            }
        ),
        create_tool(
            "module_overview",
            "列出模块中所有类和顶层函数，适合快速了解模块结构。返回：类列表和函数列表（含文件路径和行号）。参数必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "module_path": {"type": "string", "description": "模块路径，必须从代码或工具返回中获取，禁止猜测"}
                }
            }
        ),
        create_tool(
            "find_inheritance",
            "查找类的继承关系（父类/子类）。参数必须来自代码中看到的实际类名，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "类名，必须从代码中获取，禁止猜测"},
                    "direction": {"type": "string", "description": "parent 查父类, children 查子类", "default": "parent"}
                }
            }
        ),
        # 第二层：代码导航（LSP 精确定位）
        create_tool(
            "goto_definition",
            "[备用] 根据文件位置跳转到符号定义处。日常用 search_function(name) 即可。仅当多个同名符号需要按上下文消歧时使用。file 和 line 必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "文件相对路径，必须从代码或工具返回中获取"},
                    "line": {"type": "integer", "description": "行号（1-based），必须从代码或工具返回中获取"},
                    "column": {"type": "integer", "description": "列号（0-based，可选）", "default": 0}
                }
            }
        ),
        create_tool(
            "find_references",
            "查找符号在项目中的所有引用位置。用于评估改动影响范围。file 和 line 必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "文件相对路径，必须从代码或工具返回中获取"},
                    "line": {"type": "integer", "description": "行号（1-based），必须从代码或工具返回中获取"}
                }
            }
        ),
        create_tool(
            "get_call_chain",
            "获取函数的调用链（上下游关系）。用于追踪数据流和理解模块间依赖。file 和 line 必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "文件相对路径，必须从代码或工具返回中获取"},
                    "line": {"type": "integer", "description": "行号（1-based），必须从代码或工具返回中获取"},
                    "direction": {"type": "string", "description": "outgoing=它调用了谁, incoming=谁调用了它", "default": "outgoing"}
                }
            }
        ),
        # 第三层：模糊搜索（RAG，仅用于初始发现）
        create_tool(
            "find_module_summary",
            "查找模块的概述信息，包含标准流程、入口点等。这是了解'如何使用一个模块'的最佳方式。注意：返回的是已有代码的描述，仅用于理解架构，不要照搬模块名或类名到新代码中。模块名必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "module_name": {
                        "type": "string",
                        "description": "模块名，必须从代码或工具返回中获取，禁止猜测"
                    }
                }
            }
        ),
        create_tool(
            "find_class_summary",
            "查找类的概述信息，包含职责、核心方法等。注意：返回的是已有代码的描述，仅用于理解架构，不要照搬模块名或类名到新代码中。类名必须来自代码或工具返回，禁止猜测。",
            {
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "类名，必须从代码或工具返回中获取，禁止猜测"
                    }
                }
            }
        ),
        create_tool(
            "search_by_type",
            "唯一接受自然语言查询的工具。输入中文或自然语言描述，返回相关代码块。当你不知道确切的标识符名称、只知道功能描述时使用此工具。支持按 chunk_type 和 module 过滤结果。注意：返回的是已有代码的描述，仅用于理解架构，不要照搬模块名或类名到新代码中。",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自然语言查询，支持中文，如: 怪物管理、副本奖励发放、玩家升级"},
                    "chunk_type": {"type": "string", "description": "结果类型过滤: function/class_summary/module_summary，留空搜索所有类型", "default": ""},
                    "module": {"type": "string", "description": "模块名过滤（如 monster、scene），留空搜索所有模块", "default": ""},
                    "n_results": {"type": "integer", "default": 5}
                }
            }
        ),
    ]


# ===== 调用工具 =====

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """调用工具"""
    logger.info(f"[调用] {name}({arguments})")

    try:
        # 第一层：符号搜索（LSP）
        if name == "search_function":
            result = await asyncio.to_thread(lsp.search_symbol,
                arguments.get("name", ""),
                arguments.get("kind", ""))
        elif name == "list_symbols":
            result = await asyncio.to_thread(lsp.list_symbols,
                arguments.get("file", ""),
                arguments.get("kind", ""))
        elif name == "module_overview":
            result = await asyncio.to_thread(lsp.module_overview,
                arguments.get("module_path", ""))
        elif name == "find_inheritance":
            result = await asyncio.to_thread(lsp.find_inheritance,
                arguments.get("name", ""),
                arguments.get("direction", "parent"))
        # 第二层：代码导航（LSP）
        elif name == "goto_definition":
            result = await asyncio.to_thread(lsp.get_definition,
                arguments.get("file"),
                arguments.get("line"),
                arguments.get("column", 0))
        elif name == "find_references":
            result = await asyncio.to_thread(lsp.find_references,
                arguments.get("file"),
                arguments.get("line"))
        elif name == "get_call_chain":
            result = await asyncio.to_thread(lsp.get_call_chain,
                arguments.get("file"),
                arguments.get("line"),
                arguments.get("direction", "outgoing"))
        # 第三层：模糊搜索
        elif name == "find_module_summary":
            result = rag.find_module_summary(arguments.get("module_name", ""))
        elif name == "find_class_summary":
            result = rag.find_class_summary(arguments.get("class_name", ""))
        elif name == "search_by_type":
            result = rag.search_by_type(
                arguments.get("query", ""),
                chunk_type=arguments.get("chunk_type", ""),
                module=arguments.get("module", ""),
                n_results=arguments.get("n_results", 5)
            )
        # 已废弃工具（保留兼容）
        elif name == "find_by_struct":
            result = json.dumps({
                "deprecated": True,
                "message": "find_by_struct 已废弃，请使用 search_function(name) 按名称搜索类，或 list_symbols(file) 列出文件中的类和方法",
                "alternative": "search_function / list_symbols"
            }, ensure_ascii=False)
        elif name == "find_by_pattern":
            result = json.dumps({
                "deprecated": True,
                "message": "find_by_pattern 已废弃，请使用 search_function(name) 或 search_by_type(query) 替代",
                "alternative": "search_function / search_by_type"
            }, ensure_ascii=False)
        elif name == "find_function":
            result = json.dumps({
                "deprecated": True,
                "message": "find_function 已废弃，请使用 search_by_type(query, module=module) 替代",
                "alternative": "search_by_type"
            }, ensure_ascii=False)
        else:
            result = f'{{"error": "未知工具: {name}"}}'

        logger.info(f"[成功] {name} - 返回 {len(result)} 字符")
        return [TextContent(type="text", text=result)]

    except Exception as e:
        error_msg = f'{{"error": "{str(e)}"}}'
        logger.error(f"[错误] {name} - {e}")
        import traceback
        logger.error(traceback.format_exc())
        return [TextContent(type="text", text=error_msg)]


# ===== 运行服务器 =====

async def main():
    """主函数"""
    from mcp.server.stdio import stdio_server
    from mcp.server.lowlevel import NotificationOptions

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="game_server_rag",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )

if __name__ == '__main__':
    asyncio.run(main())
