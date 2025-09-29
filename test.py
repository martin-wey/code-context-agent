import asyncio

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def test_mcp_server():
    server_params = StdioServerParameters(
        command="python",
        args=["main.py", "data/R2Vul"],
    )

    print("🚀 Connecting to MCP server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                name="function_definition",
                arguments={
                    "function_name": "add_samples",
                    "language": "python",
                    "target_files": ["src/data_utils.py"],
                },
            )

            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
