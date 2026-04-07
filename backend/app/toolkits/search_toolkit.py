"""Cape-agent search toolkit.

Thin wrapper around CAMEL-AI's SearchToolkit that exposes exactly one
search tool to the agent: `search_google` if Google Custom Search keys
are configured, otherwise `search_duckduckgo` as a zero-config fallback.
"""

import os

from camel.toolkits import FunctionTool
from camel.toolkits import SearchToolkit as CamelSearchToolkit


class SearchToolkit:
    """Picks Google or DuckDuckGo based on environment variables.

    The agent never sees both — exactly one search tool is registered,
    decided at agent-creation time.
    """

    @classmethod
    def get_can_use_tools(cls) -> list[FunctionTool]:
        camel = CamelSearchToolkit()
        if os.getenv("GOOGLE_API_KEY") and os.getenv("SEARCH_ENGINE_ID"):
            return [FunctionTool(camel.search_google)]
        return [FunctionTool(camel.search_duckduckgo)]
