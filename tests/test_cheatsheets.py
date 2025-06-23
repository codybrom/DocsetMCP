#!/usr/bin/env python3
"""
Test suite for docsetmcp cheatsheet functionality
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsetmcp.server import (
    CheatsheetExtractor,
    search_cheatsheet,
    list_available_cheatsheets,
)
import docsetmcp.server


class TestCheatsheetExtractor:
    """Test CheatsheetExtractor class"""

    @patch("docsetmcp.server.Path")
    @patch("os.path.expanduser")
    def test_init_success(
        self, mock_expanduser: MagicMock, mock_path_class: MagicMock
    ) -> None:
        """Test successful initialization"""
        mock_expanduser.return_value = "/mock/path"

        # Create mock path instances
        mock_cheatsheets_path = MagicMock()
        mock_cheatsheet_dir = MagicMock()
        mock_docset = MagicMock()

        # Configure Path class to return our mock
        mock_path_class.return_value = mock_cheatsheets_path

        # Setup the directory finding
        mock_cheatsheets_path.__truediv__.return_value = mock_cheatsheet_dir
        mock_cheatsheet_dir.exists.return_value = True

        # Mock glob to return docset
        mock_cheatsheet_dir.glob.return_value = [mock_docset]

        # Create extractor
        extractor = CheatsheetExtractor("git")
        assert extractor.name == "git"
        assert extractor.docset == mock_docset

    def test_find_cheatsheet_dir_variations(self):
        """Test the _find_cheatsheet_dir method with various name patterns"""
        # Create a real instance with mocked path
        with patch("os.path.expanduser") as mock_expanduser:
            mock_expanduser.return_value = "/test/path"

            # Mock the Path class at module level
            with patch("docsetmcp.server.Path") as mock_path_class:
                # Create mock paths
                mock_base_path = MagicMock()
                mock_path_class.return_value = mock_base_path

                # Create mock directories
                git_dir = MagicMock()
                git_dir.name = "Git"
                git_dir.is_dir.return_value = True

                vim_dir = MagicMock()
                vim_dir.name = "Vim"
                vim_dir.is_dir.return_value = True

                bash_test_dir = MagicMock()
                bash_test_dir.name = "Bash Test Operators"
                bash_test_dir.is_dir.return_value = True

                # Setup iterdir to return our mock directories
                mock_base_path.iterdir.return_value = [git_dir, vim_dir, bash_test_dir]

                # Test exact match
                test_path = MagicMock()
                test_path.exists.return_value = True
                mock_base_path.__truediv__.return_value = test_path

                # Need to patch CheatsheetExtractor's __init__ to test just _find_cheatsheet_dir
                def mock_init(self: CheatsheetExtractor, name: str) -> None:
                    setattr(self, "cheatsheets_path", mock_base_path)

                with patch.object(
                    CheatsheetExtractor,
                    "__init__",
                    mock_init,
                ):
                    extractor = CheatsheetExtractor("dummy")

                    # Test direct match
                    find_method = getattr(extractor, "_find_cheatsheet_dir")
                    result = find_method("Git")
                    assert result == test_path

                    # Test case insensitive - need exists to return False for direct path
                    test_path.exists.return_value = False
                    result = find_method("git")
                    assert result == git_dir

                    # Test fuzzy match
                    result = find_method("bash")
                    assert result == bash_test_dir

    @patch("sqlite3.connect")
    @patch("builtins.open", create=True)
    @patch("pathlib.Path.exists")
    def test_search_categories(
        self, mock_exists: MagicMock, mock_open: MagicMock, mock_connect: MagicMock
    ) -> None:
        """Test searching for categories"""
        # Mock database results
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Configuration", "Category", "index.html#config"),
            ("Branches", "Category", "index.html#branches"),
        ]
        mock_connect.return_value.cursor.return_value = mock_cursor
        mock_connect.return_value.close = Mock()

        # Mock file system for get_full_content
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = """
        <html>
        <h1>Git Cheatsheet</h1>
        <section class="category">
            <h2>Configuration</h2>
            <tr><div class="name"><p>Set username</p></div><div class="notes">git config user.name</div></tr>
        </section>
        <section class="category">
            <h2>Branches</h2>
            <tr><div class="name"><p>Create branch</p></div><div class="notes">git checkout -b</div></tr>
        </section>
        </html>
        """

        # Create extractor with mocked initialization
        def mock_init(self: CheatsheetExtractor, name: str) -> None:
            pass

        with patch.object(CheatsheetExtractor, "__init__", mock_init):
            extractor = CheatsheetExtractor("git")
            extractor.name = "Git"
            extractor.db_path = Path("/mock/path/db")
            extractor.documents_path = Path("/mock/path/docs")

            result = extractor.search()

            assert "# Git" in result
            assert "Configuration" in result
            assert "Branches" in result

    @patch("builtins.open", create=True)
    @patch("pathlib.Path.exists")
    def test_extract_entry_content(
        self, mock_exists: MagicMock, mock_open: MagicMock
    ) -> None:
        """Test extracting content from HTML"""
        mock_exists.return_value = True

        html_content = """
        <tr>
            <td class="description">Create branch</td>
            <td class="command">git checkout -b new-branch</td>
        </tr>
        """

        mock_open.return_value.__enter__.return_value.read.return_value = html_content

        def mock_init2(self: CheatsheetExtractor, name: str) -> None:
            pass

        with patch.object(CheatsheetExtractor, "__init__", mock_init2):
            extractor = CheatsheetExtractor("git")
            extractor.documents_path = Path("/mock/docs")

            extract_method = getattr(extractor, "_extract_entry_content")
            result = extract_method("index.html", "Create branch")
            assert result == "```\ngit checkout -b new-branch\n```"


class TestCheatsheetMCPTools:
    """Test MCP tool functions"""

    def test_search_cheatsheet_success(self) -> None:
        """Test successful cheatsheet search"""
        # Clear existing extractors
        # Access the global extractors dict from server module
        if hasattr(docsetmcp.server, "cheatsheet_extractors"):
            docsetmcp.server.cheatsheet_extractors.clear()

        with patch("docsetmcp.server.CheatsheetExtractor") as mock_class:
            mock_instance = MagicMock()
            mock_instance.search.return_value = "# Git Cheatsheet\n## Results"
            mock_class.return_value = mock_instance

            result = search_cheatsheet("git", query="branch")

            assert "# Git Cheatsheet" in result
            assert "## Results" in result
            mock_instance.search.assert_called_once_with("branch", "", 10)

    def test_search_cheatsheet_not_found(self) -> None:
        """Test cheatsheet not found"""
        # Access the global extractors dict from server module
        if hasattr(docsetmcp.server, "cheatsheet_extractors"):
            docsetmcp.server.cheatsheet_extractors.clear()

        with patch("docsetmcp.server.CheatsheetExtractor") as mock_class:
            mock_class.side_effect = FileNotFoundError("Not found")

            with patch("docsetmcp.server.list_available_cheatsheets") as mock_list:
                mock_list.return_value = "Available: Git, Vim"

                result = search_cheatsheet("nonexistent")
                assert "Error: Cheatsheet 'nonexistent' not found" in result
                assert "Available: Git, Vim" in result

    def test_search_cheatsheet_cached(self) -> None:
        """Test using cached cheatsheet extractor"""
        # Add a mock extractor to cache
        mock_extractor = MagicMock()
        mock_extractor.search.return_value = "Cached result"
        # Add to the global extractors dict
        if hasattr(docsetmcp.server, "cheatsheet_extractors"):
            docsetmcp.server.cheatsheet_extractors["git"] = mock_extractor

        result = search_cheatsheet("git")
        assert result == "Cached result"

        # Clean up
        if hasattr(docsetmcp.server, "cheatsheet_extractors"):
            docsetmcp.server.cheatsheet_extractors.clear()

    def test_search_invalid_max_results(self) -> None:
        """Test invalid max_results parameter"""
        result = search_cheatsheet("git", max_results=100)
        assert "Error: max_results must be between 1 and 50" in result

        result = search_cheatsheet("git", max_results=0)
        assert "Error: max_results must be between 1 and 50" in result

    @patch("os.path.expanduser")
    @patch("docsetmcp.server.Path")
    def test_list_available_cheatsheets(
        self, mock_path_class: MagicMock, mock_expanduser: MagicMock
    ) -> None:
        """Test listing available cheatsheets"""
        mock_expanduser.return_value = "/mock/path"

        # Create mock path
        mock_path = MagicMock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True

        # Create mock directories with sorting support
        git_dir = MagicMock()
        git_dir.name = "Git"
        git_dir.is_dir.return_value = True
        git_dir.glob.return_value = [MagicMock()]  # Has docset

        def git_lt(self: MagicMock, other: MagicMock) -> bool:
            return self.name < other.name

        git_dir.__lt__ = git_lt

        vim_dir = MagicMock()
        vim_dir.name = "Vim"
        vim_dir.is_dir.return_value = True
        vim_dir.glob.return_value = [MagicMock()]  # Has docset

        def vim_lt(self: MagicMock, other: MagicMock) -> bool:
            return self.name < other.name

        vim_dir.__lt__ = vim_lt

        empty_dir = MagicMock()
        empty_dir.name = "Empty"
        empty_dir.is_dir.return_value = True
        empty_dir.glob.return_value = []  # No docset

        def empty_lt(self: MagicMock, other: MagicMock) -> bool:
            return self.name < other.name

        empty_dir.__lt__ = empty_lt

        # Make iterdir return our mocks
        mock_path.iterdir.return_value = [git_dir, vim_dir, empty_dir]

        result = list_available_cheatsheets()

        assert "Available cheatsheets:" in result
        assert "**git**: Git" in result
        assert "**vim**: Vim" in result
        assert "Empty" not in result

    @patch("os.path.expanduser")
    @patch("docsetmcp.server.Path")
    def test_list_available_cheatsheets_none(
        self, mock_path_class: MagicMock, mock_expanduser: MagicMock
    ) -> None:
        """Test when no cheatsheets exist"""
        mock_expanduser.return_value = "/mock/path"

        mock_path = MagicMock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = []

        result = list_available_cheatsheets()
        assert "No cheatsheets found" in result

    @patch("os.path.expanduser")
    @patch("docsetmcp.server.Path")
    def test_list_available_cheatsheets_no_dir(
        self, mock_path_class: MagicMock, mock_expanduser: MagicMock
    ) -> None:
        """Test when cheatsheets directory doesn't exist"""
        mock_expanduser.return_value = "/mock/path"

        mock_path = MagicMock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = False

        result = list_available_cheatsheets()
        assert "Cheatsheets directory not found" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
