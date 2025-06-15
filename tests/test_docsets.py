#!/usr/bin/env python3
"""
Test suite for dashmcp docset configurations
"""

import os
import sys
import pytest
import yaml
import sqlite3
from pathlib import Path
from typing import Dict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashmcp.server import DashExtractor


class TestDocsets:
    """Test all docset configurations"""

    @classmethod
    def setup_class(cls):
        """Setup test data"""
        cls.config_dir = Path(__file__).parent.parent / "dashmcp" / "config" / "docsets"
        cls.yaml_files = sorted(
            list(cls.config_dir.glob("*.yaml")) + list(cls.config_dir.glob("*.yml"))
        )

    def load_yaml_config(self, yaml_path: Path) -> Dict:
        """Load YAML configuration file"""
        with open(yaml_path, "r") as f:
            return yaml.safe_load(f)

    @pytest.mark.parametrize(
        "yaml_path",
        [
            pytest.param(p, id=p.name)
            for p in sorted(
                (Path(__file__).parent.parent / "dashmcp" / "config" / "docsets").glob(
                    "*.y*ml"
                )
            )
        ],
    )
    def test_docset_exists(self, yaml_path: Path):
        """Test that each configured docset actually exists"""
        config = self.load_yaml_config(yaml_path)

        # Build the expected docset path
        dash_docsets_path = os.path.expanduser(
            "~/Library/Application Support/Dash/DocSets"
        )
        docset_folder = config.get("docset_name", "")
        docset_file = config.get("docset_path", "")
        full_docset_path = Path(dash_docsets_path) / docset_folder / docset_file

        if not full_docset_path.exists():
            pytest.skip(f"Docset not installed: {config.get('name', docset_folder)}")

    @pytest.mark.parametrize(
        "yaml_path",
        [
            pytest.param(p, id=p.name)
            for p in sorted(
                (Path(__file__).parent.parent / "dashmcp" / "config" / "docsets").glob(
                    "*.y*ml"
                )
            )
        ],
    )
    def test_docset_search(self, yaml_path: Path):
        """Test that each docset can be searched successfully"""
        from dashmcp.config_loader import ConfigLoader

        # Load config through ConfigLoader to get defaults applied
        loader = ConfigLoader()
        docset_name = yaml_path.stem
        config = loader.load_config(docset_name)

        # Skip if disabled
        if not config.get("enabled", True):
            pytest.skip(f"Docset {config.get('name')} is disabled")

        docset_folder = config.get("docset_name", "")

        # Import the test extractor
        from tests.helpers import TestDashExtractor

        # Create extractor instance - skip if docset not found
        try:
            extractor = TestDashExtractor(docset_folder, config)
        except FileNotFoundError:
            pytest.skip(f"Docset not installed: {config.get('name', docset_folder)}")

        # Try various common search queries
        test_queries = [
            "get",
            "set",
            "create",
            "init",
            "new",
            "class",
            "function",
            "method",
            "type",
            "a",
        ]

        found_results = False
        for query in test_queries:
            try:
                results = extractor.search(query, limit=5)
                if results:
                    found_results = True
                    break
            except Exception:
                continue

        assert (
            found_results
        ), f"No search results found for any test query in {config.get('name')}"

    @pytest.mark.parametrize(
        "yaml_path",
        [
            pytest.param(p, id=p.name)
            for p in sorted(
                (Path(__file__).parent.parent / "dashmcp" / "config" / "docsets").glob(
                    "*.y*ml"
                )
            )
        ],
    )
    def test_docset_types(self, yaml_path: Path):
        """Test that all configured types exist in the docset"""
        from dashmcp.config_loader import ConfigLoader

        # Load config through ConfigLoader to get defaults applied
        loader = ConfigLoader()
        docset_name = yaml_path.stem
        config = loader.load_config(docset_name)

        # Skip if disabled
        if not config.get("enabled", True):
            pytest.skip(f"Docset {config.get('name')} is disabled")

        # Get configured types (excluding 'default')
        types_dict = config.get("types", {})
        configured_types = [t for t in types_dict.keys() if t != "default"]

        if not configured_types:
            pytest.skip("No types configured")

        # Build database path
        dash_docsets_path = os.path.expanduser(
            "~/Library/Application Support/Dash/DocSets"
        )
        docset_folder = config.get("docset_name", "")
        docset_file = config.get("docset_path", "")
        db_path = (
            Path(dash_docsets_path)
            / docset_folder
            / docset_file
            / "Contents/Resources/optimizedIndex.dsidx"
        )

        # Skip if database doesn't exist
        if not db_path.exists():
            pytest.skip(f"Docset not installed: {config.get('name', docset_folder)}")

        # Query the database for all types - skip if database is invalid
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT DISTINCT type 
                FROM searchIndex 
                WHERE type != ''
            """
            )

            existing_types = {row[0] for row in cursor.fetchall()}
            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            pytest.skip(f"Database error for {config.get('name', docset_folder)}: {e}")

        # Check each configured type
        missing_types = []
        for configured_type in configured_types:
            if configured_type not in existing_types:
                missing_types.append(configured_type)

        assert (
            not missing_types
        ), f"Missing types: {missing_types}. Existing types: {sorted(existing_types)}"

    def test_yaml_structure(self):
        """Test that all YAML files have the required structure"""
        from dashmcp.config_loader import ConfigLoader

        required_fields = [
            "name",
            "docset_name",
            "docset_path",
            "format",
            "enabled",
            "languages",
            "types",  # Updated from type_priority to types
        ]

        loader = ConfigLoader()
        for yaml_path in self.yaml_files:
            # Load through ConfigLoader to get defaults applied
            docset_name = yaml_path.stem
            config = loader.load_config(docset_name)

            # Check required fields
            for field in required_fields:
                assert (
                    field in config
                ), f"{yaml_path.name} missing required field: {field}"

            # Check format is valid
            assert config["format"] in [
                "apple",
                "tarix",
            ], f"{yaml_path.name} has invalid format: {config['format']}"

            # Check languages structure
            assert isinstance(
                config["languages"], dict
            ), f"{yaml_path.name} languages must be a dict"
            assert (
                len(config["languages"]) > 0
            ), f"{yaml_path.name} must have at least one language"

            # Check types structure
            assert isinstance(
                config["types"], dict
            ), f"{yaml_path.name} types must be a dict"
            assert (
                "default" in config["types"]
            ), f"{yaml_path.name} types must have 'default'"

    def test_no_duplicate_names(self):
        """Test that there are no duplicate docset names"""
        names = []
        for yaml_path in self.yaml_files:
            config = self.load_yaml_config(yaml_path)
            names.append(config.get("name", ""))

        duplicates = [name for name in names if names.count(name) > 1]
        assert not duplicates, f"Duplicate docset names found: {set(duplicates)}"

    def test_server_initialization(self):
        """Test that the server can initialize with each docset"""
        # Get list of docsets that should work
        working_docsets = []

        for yaml_path in self.yaml_files:
            config = self.load_yaml_config(yaml_path)
            if config.get("enabled", True):
                # Extract docset type from filename
                docset_type = yaml_path.stem

                # Check if docset exists
                dash_docsets_path = os.path.expanduser(
                    "~/Library/Application Support/Dash/DocSets"
                )
                docset_folder = config.get("docset_name", "")
                docset_file = config.get("docset_path", "")
                full_docset_path = Path(dash_docsets_path) / docset_folder / docset_file

                if full_docset_path.exists():
                    working_docsets.append(docset_type)

        # Test initialization (we can't easily test all without modifying server.py)
        # Just ensure at least one works
        assert len(working_docsets) > 0, "No working docsets found"


class TestDocsetContent:
    """Test actual content extraction from docsets"""

    def test_apple_documentation(self):
        """Test Apple documentation extraction"""
        try:
            extractor = DashExtractor("apple")
            result = extractor.search("URLSession", language="swift", max_results=1)
            assert "URLSession" in result
            assert "class" in result.lower() or "protocol" in result.lower()
        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_nodejs_documentation(self):
        """Test Node.js documentation extraction"""
        try:
            extractor = DashExtractor("nodejs")
            result = extractor.search("readFile", language="javascript", max_results=1)
            assert "readFile" in result or "fs" in result
        except (FileNotFoundError, ValueError):
            pytest.skip("Node.js docset not installed")

    def test_python_documentation(self):
        """Test Python documentation extraction"""
        # Try both Python 3 and general Python
        for docset_name in ["python_3", "python3", "python"]:
            try:
                extractor = DashExtractor(docset_name)
                result = extractor.search("list", language="python", max_results=1)
                assert "list" in result.lower()
                return  # Success, exit
            except (FileNotFoundError, ValueError):
                continue

        pytest.skip("Python docset not installed")


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_nonexistent_docset(self):
        """Test handling of non-existent docset"""
        with pytest.raises(ValueError, match="Unsupported docset type"):
            DashExtractor("nonexistent_docset_12345")

    def test_empty_search_query(self):
        """Test handling of empty search query"""
        try:
            extractor = DashExtractor("apple")
            result = extractor.search("", language="swift", max_results=1)
            # Should return no results or error message
            assert (
                "No matches found" in result
                or "Error" in result
                or "couldn't extract documentation" in result
            )
        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_special_characters_in_search(self):
        """Test handling of special characters in search"""
        try:
            extractor = DashExtractor("apple")
            # Test with various special characters
            for query in ["@#$%", "<<<", "'''", '"""']:
                result = extractor.search(query, language="swift", max_results=1)
                # Should handle gracefully without crashing
                assert isinstance(result, str)
        except FileNotFoundError:
            pytest.skip("Apple docset not installed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
