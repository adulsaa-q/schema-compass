"""Schema topology navigator and AST safety gateway, served over MCP."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("schema-compass")
except PackageNotFoundError:  # running from a bare source tree, not installed
    __version__ = "0+unknown"
