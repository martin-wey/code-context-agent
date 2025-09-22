import asyncio
import os
import json
from typing import Any, List, Optional, Dict
from pathlib import Path
from pydantic import BaseModel, Field

from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.tools import JSONToolOutput, Tool, ToolRunOptions
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult
from beeai_framework.tools.mcp import MCPTool


class AstGrepMCPManager:
    """Manages ast-grep MCP server connection and tools"""

    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path).resolve()
        self._session: Optional[ClientSession] = None
        self._available_tools: List[MCPTool] = []

    async def connect(self) -> bool:
        try:
            server_params = StdioServerParameters(
                command="docker",
                args=[
                    "run", "-i", "--rm",
                    "-v", f"{self.codebase_path}:/workspace",
                    "-w", "/workspace",
                    "mcp/ast-grep"
                ],
                env={
                    "AST_GREP_PATH": "/workspace"
                }
            )
            self._available_tools = await MCPTool.from_client(stdio_client(server_params))

            print(f"✅ Connected to ast-grep MCP server")
            print(f"📋 Available tools: {[tool.name for tool in self._available_tools]}")

            return True

        except Exception as e:
            print(f"❌ Failed to connect to MCP server: {e}")
            return False

    async def execute_pattern(
        self,
        pattern: str,
        language: str = "python",
        files: Optional[List[str]] = None
    ) -> None:
        """Execute ast-grep pattern using the first available tool"""

        if not self._available_tools:
            print("❌ No MCP tools available. Call connect() first.")
            return []

        ast_grep_tool = self._available_tools[0]
        try:
            args = [
                "run",  # ast-grep run command
                "-l", language,  # language flag
                "--pattern", "$NAME = $VAL",  # pattern to search
                "--json"  # output format
            ]
            if files:
                args.extend(files)
            else:
                args.append(".")  # Default to current directory

            print(f"🚀 Executing: ast-grep {' '.join(args)}")

            tool_input_data = ast_grep_tool.input_schema(args=args)
            result = await ast_grep_tool._run(
                input_data=tool_input_data,
                options=None,
                context=None
            )


            exit(1)

        except Exception as e:
            print(f"❌ Error executing pattern '{pattern}': {e}")
            print(f"🔍 Tool schema: {ast_grep_tool.input_schema}")
            return []


class BaseSimplifiedMCPTool(Tool):
    """Base class for simplified MCP ast-grep tools"""

    def __init__(self, codebase_path: str, options: dict[str, Any] | None = None):
        super().__init__(options)
        self.codebase_path = Path(codebase_path).resolve()
        self.mcp_manager = AstGrepMCPManager(codebase_path)
        self._connected = False

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(
            namespace=["tool", "simplified_mcp", "astgrep", self.name.lower()],
            creator=self,
        )

    async def _ensure_connection(self) -> bool:
        """Ensure MCP connection is established"""
        if not self._connected:
            self._connected = await self.mcp_manager.connect()
        return self._connected

    async def _execute_template_pattern(
        self,
        pattern: str,
        language: str,
        files: Optional[List[str]] = None,
        context: RunContext = None
    ) -> None:
        """Execute ast-grep template pattern"""

        emitter = self._create_emitter()
        # await emitter.emit(f"Executing pattern: {pattern}")

        # Ensure connection
        if not await self._ensure_connection():
            # await emitter.emit("❌ Failed to establish MCP connection")
            return []

        # Execute pattern
        matches = await self.mcp_manager.execute_pattern(
            pattern=pattern,
            language=language,
            files=files
        )

        # await emitter.emit(f"Found {len(matches)} matches")
        return matches


class FunctionDefinitionInput(BaseModel):
    function_name: str = Field(description="Name of the function to find")
    language: str = Field(description="Programming language", default="python")
    target_files: Optional[List[str]] = Field(description="Specific files to search", default=None)


class SimplifiedFunctionDefinitionTool(BaseSimplifiedMCPTool):
    """Find function definitions using simplified MCP approach"""

    name = "SimplifiedFunctionDefinition"
    description = (
        "Find function definitions by name using ast-grep MCP server. "
        "Template: function-definition"
    )
    input_schema = FunctionDefinitionInput

    async def _run(
        self,
        input: FunctionDefinitionInput,
        options: ToolRunOptions | None,
        context: RunContext
    ) -> None:
        # Template: function-definition pattern
        pattern = f"def {input.function_name}(...): ..."

        matches = await self._execute_template_pattern(
            pattern=pattern,
            language=input.language,
            files=input.target_files,
            context=context
        )

        return None

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(
            namespace=["tool", "simplified_mcp", "astgrep", self.name.lower()],
            creator=self,
        )


async def main() -> None:
    tool = SimplifiedFunctionDefinitionTool(codebase_path="data/R2Vul")

    test_input = FunctionDefinitionInput(
        function_name="main",
        language="python",
        target_files=["merge.py"]
    )

    try:
        result = await tool._run(test_input, None, None)
        print(f"✅ Tool executed successfully")
        print(result)
        print(f"📋 Result: {result.result}")
    except Exception as e:
        print(f"❌ Tool execution failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())