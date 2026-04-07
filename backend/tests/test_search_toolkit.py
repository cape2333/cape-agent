"""Tests for app.toolkits.search_toolkit.SearchToolkit.get_can_use_tools()."""

from app.toolkits.search_toolkit import SearchToolkit


class TestGetCanUseTools:
    def test_returns_google_when_both_keys_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.setenv("SEARCH_ENGINE_ID", "fake-cx")
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_google"

    def test_returns_duckduckgo_when_no_google_keys(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"

    def test_returns_duckduckgo_when_only_google_api_key_set(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
        monkeypatch.delenv("SEARCH_ENGINE_ID", raising=False)
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"

    def test_returns_duckduckgo_when_only_search_engine_id_set(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("SEARCH_ENGINE_ID", "fake-cx")
        tools = SearchToolkit.get_can_use_tools()
        assert len(tools) == 1
        assert tools[0].get_function_name() == "search_duckduckgo"
