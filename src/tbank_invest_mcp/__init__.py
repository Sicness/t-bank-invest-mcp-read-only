"""MCP server for T-Bank (Tinkoff) Invest API — read-only portfolio analytics."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("t-bank-invest-mcp-read-only")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0+unknown"
