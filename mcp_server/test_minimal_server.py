#!/usr/bin/env python3
"""
最小化 MCP 服务器测试
"""
import asyncio
from mcp.server import Server
from mcp.server.models import InitializationOptions

server = Server("test")

async def main():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="test",
                server_version="1.0.0",
                capabilities=server.get_capabilities()
            )
        )

if __name__ == '__main__':
    asyncio.run(main())
