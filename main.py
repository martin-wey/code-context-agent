import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.tools import Tool, ToolRunOptions, JSONToolOutput
from beeai_framework.tools.mcp import MCPTool
from fastmcp import FastMCP
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field


class CodeMatch(BaseModel):
    """Represents a code match from ast-grep"""

    file_path: str = Field(description="Path to the file containing the match")
    byte_start: int = Field(description="Starting byte offset")
    byte_end: int = Field(description="Ending byte offset")
    code_snippet: str = Field(description="The matched code snippet")
    pattern: str = Field(description="The pattern that matched")


class AstGrepResults(BaseModel):
    """Container for ast-grep results"""

    matches: List[CodeMatch] = Field(description="List of code matches")


class AstGrepMCPManager:
    """Manages ast-grep MCP server connection and tools
    https://hub.docker.com/r/mcp/ast-grep
    """

    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path).resolve()
        self._available_tools: List[MCPTool] = []

    async def connect(self) -> bool:
        try:
            server_params = StdioServerParameters(
                command="docker",
                args=[
                    "run",
                    "-i",
                    "--rm",
                    "-v",
                    f"{self.codebase_path}:/workspace",
                    "-w",
                    "/workspace",
                    "mcp/ast-grep",
                ],
                env={"AST_GREP_PATH": "/workspace"},
            )
            self._available_tools = await MCPTool.from_client(
                stdio_client(server_params)
            )

            print(f"✅ Connected to ast-grep MCP server")
            print(
                f"📋 Available tools: {[tool.name for tool in self._available_tools]}"
            )

            return True

        except Exception as e:
            print(f"❌ Failed to connect to MCP server: {e}")
            return False

    async def execute_pattern(
        self, pattern: str, language: str = "python", files: Optional[List[str]] = None
    ) -> List[CodeMatch]:
        """Execute ast-grep pattern using the first available tool"""

        if not self._available_tools:
            print("❌ No MCP tools available. Call connect() first.")
            return []

        ast_grep_tool = self._available_tools[0]
        try:
            args = [
                "run",  # ast-grep run command
                "-l",
                language,
                "--pattern",
                pattern,  # pattern to search
                "--json",
            ]
            if files:
                args.extend(files)
            else:
                args.append(".")  # Default to current directory

            print(f"🚀 Executing: ast-grep {' '.join(args)}")

            tool_input_data = ast_grep_tool.input_schema(args=args)
            result = await ast_grep_tool._run(
                input_data=tool_input_data, options=None, context=None
            )

            result = result.to_json_safe()[0]
            result = json.loads(result.text)

            matches = []
            for res in result:
                matches.append(
                    CodeMatch(
                        file_path=res["file"],
                        byte_start=res["range"]["byteOffset"]["start"],
                        byte_end=res["range"]["byteOffset"]["end"],
                        code_snippet=res["text"],
                        pattern=pattern,
                    )
                )
            return matches

        except Exception as e:
            print(f"❌ Error executing pattern '{pattern}': {e}")
            print(f"🔍 Tool schema: {ast_grep_tool.input_schema}")
            # return await self._fallback_execution(pattern, language, files)
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
            namespace=["tool", "ast-grep", self.name.lower()],
            creator=self,
        )

    async def _ensure_connection(self) -> bool:
        if not self._connected:
            self._connected = await self.mcp_manager.connect()
        return self._connected

    async def _execute_template_pattern(
        self,
        pattern: str,
        language: str,
        files: Optional[List[str]] = None,
        context: Optional[RunContext] = None,
    ) -> List[CodeMatch]:
        if not await self._ensure_connection():
            return []

        return await self.mcp_manager.execute_pattern(
            pattern=pattern, language=language, files=files
        )


class FunctionDefinitionInput(BaseModel):
    function_name: str = Field(description="Name of the function to find")
    language: str = Field(description="Programming language", default="python")
    target_files: Optional[List[str]] = Field(
        description="Specific files to search", default=None
    )


class SimplifiedFunctionDefinitionTool(BaseSimplifiedMCPTool):
    """Find function definitions using simplified MCP approach"""

    name = "SimplifiedFunctionDefinition"
    description = "Find function definitions by name using ast-grep"
    input_schema = FunctionDefinitionInput

    async def _run(
        self,
        input: FunctionDefinitionInput,
        options: Optional[ToolRunOptions],
        context: Optional[RunContext],
    ) -> JSONToolOutput:
        pattern = f"def {input.function_name}($$$ARGS): $$$BODY"

        matches = await self._execute_template_pattern(
            pattern=pattern,
            language=input.language,
            files=input.target_files,
            context=context,
        )

        result = AstGrepResults(matches=matches)
        return JSONToolOutput(result=result.model_dump())


if len(sys.argv) > 1:
    codebase_path = sys.argv[1]
else:
    codebase_path = "data/R2Vul"

mcp = FastMCP("ast-grep-templates")
function_definition_tool = SimplifiedFunctionDefinitionTool(codebase_path=codebase_path)


@mcp.tool()
async def function_definition(
    function_name: str,
    language: str = "python",
    target_files: Optional[List[str]] = None,
) -> dict:
    input_data = FunctionDefinitionInput(
        function_name=function_name, language=language, target_files=target_files
    )

    result = await function_definition_tool._run(
        input=input_data, options=None, context=None
    )

    return result.to_json_safe()


if __name__ == "__main__":
    mcp.run()
