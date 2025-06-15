#!/usr/bin/env python3
"""
Test suite for dashmcp cheatsheet functionality
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashmcp.server import (
    CheatsheetExtractor,
    search_cheatsheet,
    list_available_cheatsheets,
    cheatsheet_extractors,
)


class TestCheatsheetExtractor:
    """Test CheatsheetExtractor class"""

    @patch("dashmcp.server.Path")
    @patch("os.path.expanduser")
    def test_init_success(self, mock_expanduser, mock_path_class):
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
            with patch("dashmcp.server.Path") as mock_path_class:
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
                with patch.object(
                    CheatsheetExtractor,
                    "__init__",
                    lambda self, name: setattr(
                        self, "cheatsheets_path", mock_base_path
                    ),
                ):
                    extractor = CheatsheetExtractor("dummy")

                    # Test direct match
                    result = extractor._find_cheatsheet_dir("Git")
                    assert result == test_path

                    # Test case insensitive - need exists to return False for direct path
                    test_path.exists.return_value = False
                    result = extractor._find_cheatsheet_dir("git")
                    assert result == git_dir

                    # Test fuzzy match
                    result = extractor._find_cheatsheet_dir("bash")
                    assert result == bash_test_dir

    @patch("sqlite3.connect")
    @patch("builtins.open", create=True)
    @patch("pathlib.Path.exists")
    def test_search_categories(self, mock_exists, mock_open, mock_connect):
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
        with patch.object(CheatsheetExtractor, "__init__", lambda self, name: None):
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
    def test_extract_entry_content(self, mock_exists, mock_open):
        """Test extracting content from HTML"""
        mock_exists.return_value = True

        html_content = """
        <tr>
            <td class="description">Create branch</td>
            <td class="command">git checkout -b new-branch</td>
        </tr>
        """

        mock_open.return_value.__enter__.return_value.read.return_value = html_content

        with patch.object(CheatsheetExtractor, "__init__", lambda self, name: None):
            extractor = CheatsheetExtractor("git")
            extractor.documents_path = Path("/mock/docs")

            result = extractor._extract_entry_content("index.html", "Create branch")
            assert result == "```\ngit checkout -b new-branch\n```"


class TestCheatsheetMCPTools:
    """Test MCP tool functions"""

    def test_search_cheatsheet_success(self):
        """Test successful cheatsheet search"""
        # Clear any existing extractors
        cheatsheet_extractors.clear()

        with patch("dashmcp.server.CheatsheetExtractor") as mock_class:
            mock_instance = MagicMock()
            mock_instance.search.return_value = "# Git Cheatsheet\n## Results"
            mock_class.return_value = mock_instance

            result = search_cheatsheet("git", query="branch")

            assert "# Git Cheatsheet" in result
            assert "## Results" in result
            mock_instance.search.assert_called_once_with("branch", "", 10)

    def test_search_cheatsheet_not_found(self):
        """Test cheatsheet not found"""
        cheatsheet_extractors.clear()

        with patch("dashmcp.server.CheatsheetExtractor") as mock_class:
            mock_class.side_effect = FileNotFoundError("Not found")

            with patch("dashmcp.server.list_available_cheatsheets") as mock_list:
                mock_list.return_value = "Available: Git, Vim"

                result = search_cheatsheet("nonexistent")
                assert "Error: Cheatsheet 'nonexistent' not found" in result
                assert "Available: Git, Vim" in result

    def test_search_cheatsheet_cached(self):
        """Test using cached cheatsheet extractor"""
        # Add a mock extractor to cache
        mock_extractor = MagicMock()
        mock_extractor.search.return_value = "Cached result"
        cheatsheet_extractors["git"] = mock_extractor

        result = search_cheatsheet("git")
        assert result == "Cached result"

        # Clean up
        cheatsheet_extractors.clear()

    def test_search_invalid_max_results(self):
        """Test invalid max_results parameter"""
        result = search_cheatsheet("git", max_results=100)
        assert "Error: max_results must be between 1 and 50" in result

        result = search_cheatsheet("git", max_results=0)
        assert "Error: max_results must be between 1 and 50" in result

    @patch("os.path.expanduser")
    @patch("dashmcp.server.Path")
    def test_list_available_cheatsheets(self, mock_path_class, mock_expanduser):
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
        git_dir.__lt__ = lambda self, other: self.name < other.name

        vim_dir = MagicMock()
        vim_dir.name = "Vim"
        vim_dir.is_dir.return_value = True
        vim_dir.glob.return_value = [MagicMock()]  # Has docset
        vim_dir.__lt__ = lambda self, other: self.name < other.name

        empty_dir = MagicMock()
        empty_dir.name = "Empty"
        empty_dir.is_dir.return_value = True
        empty_dir.glob.return_value = []  # No docset
        empty_dir.__lt__ = lambda self, other: self.name < other.name

        # Make iterdir return our mocks
        mock_path.iterdir.return_value = [git_dir, vim_dir, empty_dir]

        result = list_available_cheatsheets()

        assert "Available cheatsheets:" in result
        assert "**git**: Git" in result
        assert "**vim**: Vim" in result
        assert "Empty" not in result

    @patch("os.path.expanduser")
    @patch("dashmcp.server.Path")
    def test_list_available_cheatsheets_none(self, mock_path_class, mock_expanduser):
        """Test when no cheatsheets exist"""
        mock_expanduser.return_value = "/mock/path"

        mock_path = MagicMock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = True
        mock_path.iterdir.return_value = []

        result = list_available_cheatsheets()
        assert "No cheatsheets found" in result

    @patch("os.path.expanduser")
    @patch("dashmcp.server.Path")
    def test_list_available_cheatsheets_no_dir(self, mock_path_class, mock_expanduser):
        """Test when cheatsheets directory doesn't exist"""
        mock_expanduser.return_value = "/mock/path"

        mock_path = MagicMock()
        mock_path_class.return_value = mock_path
        mock_path.exists.return_value = False

        result = list_available_cheatsheets()
        assert "No Dash cheatsheets directory found" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
