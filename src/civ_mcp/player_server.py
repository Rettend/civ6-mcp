"""MCP entry boundary for structured, player-view gameplay tools."""

import json
import re

from mcp.server.fastmcp import FastMCP


def validate_arguments(tool_name: str, arguments: dict) -> None:
    # Reflections are stored as prose; they are never interpolated into Lua.
    prose = {"tactical", "strategic", "tooling", "planning", "hypothesis"}
    encoded = {"votes"}

    def check(value):
        if isinstance(value, str):
            if not re.fullmatch(r"[\w .,:/+\-]*", value):
                raise ValueError("Gameplay identifiers cannot contain code or quote delimiters")
        elif isinstance(value, dict):
            for key, item in value.items():
                check(key)
                check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check(item)
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ValueError("Unsupported gameplay argument")

    for key, value in arguments.items():
        if tool_name == "end_turn" and key in prose:
            continue
        if tool_name == "set_policies" and key == "assignments" and isinstance(value, str):
            if not re.fullmatch(r"\s*\d+\s*=\s*\w+(?:\s*,\s*\d+\s*=\s*\w+)*\s*", value):
                raise ValueError("Policy assignments must use slot=POLICY_TYPE pairs")
            continue
        if key in encoded and isinstance(value, str) and value.strip():
            decoded = json.loads(value)
            check(decoded)
            if not isinstance(decoded, list) or any(
                not isinstance(vote, dict) or any(type(item) is not int for item in vote.values())
                for vote in decoded
            ):
                raise ValueError("World Congress votes must be a JSON list of integer fields")
        else:
            check(value)


class PlayerViewMCP(FastMCP):
    async def call_tool(self, name, arguments):
        validate_arguments(name, arguments)
        return await super().call_tool(name, arguments)
