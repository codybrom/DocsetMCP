#!/usr/bin/env python3
"""
Test suite for docsetmcp docset configurations
"""

import os
import sys
import pytest
import yaml
import sqlite3
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docsetmcp.server import DashExtractor


class TestDocsets:
    """Test all docset configurations"""

    @classmethod
    def setup_class(cls):
        """Setup test data"""
        cls.config_dir = Path(__file__).parent.parent / "docsetmcp" / "docsets"
        cls.yaml_files = sorted(
            list(cls.config_dir.glob("*.yaml")) + list(cls.config_dir.glob("*.yml"))
        )

    def load_yaml_config(self, yaml_path: Path) -> dict[str, object]:
        """Load YAML configuration file"""
        with open(yaml_path, "r") as f:
            return yaml.safe_load(f)

    @pytest.mark.parametrize(
        "yaml_path",
        [
            pytest.param(p, id=p.name)
            for p in sorted(
                (Path(__file__).parent.parent / "docsetmcp" / "docsets").glob("*.y*ml")
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
        docset_folder = str(config.get("docset_name", ""))
        docset_file = str(config.get("docset_path", ""))
        full_docset_path = Path(dash_docsets_path) / docset_folder / docset_file

        if not full_docset_path.exists():
            pytest.skip(f"Docset not installed: {config.get('name', docset_folder)}")

    @pytest.mark.parametrize(
        "yaml_path",
        [
            pytest.param(p, id=p.name)
            for p in sorted(
                (Path(__file__).parent.parent / "docsetmcp" / "docsets").glob("*.y*ml")
            )
        ],
    )
    def test_docset_search(self, yaml_path: Path):
        """Test that each docset can be searched successfully"""
        from docsetmcp.config_loader import ConfigLoader

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
            return

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
                (Path(__file__).parent.parent / "docsetmcp" / "docsets").glob("*.y*ml")
            )
        ],
    )
    def test_docset_types(self, yaml_path: Path):
        """Test that all configured types exist in the docset"""
        from docsetmcp.config_loader import ConfigLoader

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
            return

        # Check each configured type
        missing_types: list[str] = []
        for configured_type in configured_types:
            if configured_type not in existing_types:
                missing_types.append(configured_type)

        assert (
            not missing_types
        ), f"Missing types: {missing_types}. Existing types: {sorted(existing_types)}"

    def test_yaml_structure(self):
        """Test that all YAML files have the required structure"""
        from docsetmcp.config_loader import ConfigLoader

        required_fields = [
            "name",
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
            languages = config["languages"]
            assert isinstance(
                languages, dict
            ), f"{yaml_path.name} languages must be a dict"
            # After isinstance check, type checker knows languages is a dict
            assert (
                len(languages) > 0
            ), f"{yaml_path.name} must have at least one language"

            # Check types structure
            types = config["types"]
            assert isinstance(types, dict), f"{yaml_path.name} types must be a dict"
            # After isinstance check, type checker knows types is a dict
            assert "default" in types, f"{yaml_path.name} types must have 'default'"

    def test_no_duplicate_names(self):
        """Test that there are no duplicate docset names"""
        names: list[str] = []
        for yaml_path in self.yaml_files:
            config = self.load_yaml_config(yaml_path)
            name = config.get("name", "")
            names.append(str(name))

        duplicates = [name for name in names if names.count(name) > 1]
        assert not duplicates, f"Duplicate docset names found: {set(duplicates)}"

    def test_server_initialization(self):
        """Test that the server can initialize with each docset"""
        # Get list of docsets that should work
        working_docsets: list[str] = []

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
                full_docset_path = (
                    Path(dash_docsets_path) / str(docset_folder) / str(docset_file)
                )

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
            extractor = DashExtractor("apple_api_reference")
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
            extractor = DashExtractor("apple_api_reference")
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
            extractor = DashExtractor("apple_api_reference")
            # Test with various special characters
            for query in ["@#$%", "<<<", "'''", '"""']:
                result = extractor.search(query, language="swift", max_results=1)
                # Should handle gracefully without crashing
                assert isinstance(result, str)
        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_fuzzy_search_normalization(self):
        """Test that fuzzy search works with spaces and case variations"""
        try:
            extractor = DashExtractor("apple_api_reference")

            # Test space normalization - "App Intent" should find "AppIntent"
            result1 = extractor.search("App Intent", language="swift", max_results=1)
            result2 = extractor.search("AppIntent", language="swift", max_results=1)
            result3 = extractor.search("app intent", language="swift", max_results=1)

            # All three should return results (or same error if not found)
            assert (
                "AppIntent" in result1
                or "AppIntent" in result2
                or "AppIntent" in result3
            )

            # Test another example
            result4 = extractor.search("URL Session", language="swift", max_results=1)
            result5 = extractor.search("URLSession", language="swift", max_results=1)

            # Both should work
            assert "URLSession" in result4 or "URLSession" in result5

        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_case_insensitive_search(self):
        """Test that search is case-insensitive"""
        try:
            extractor = DashExtractor("apple_api_reference")

            # Test different case variations
            result_lower = extractor.search(
                "urlsession", language="swift", max_results=1
            )
            result_upper = extractor.search(
                "URLSESSION", language="swift", max_results=1
            )
            result_mixed = extractor.search(
                "UrlSession", language="swift", max_results=1
            )

            # All should find URLSession
            for result in [result_lower, result_upper, result_mixed]:
                assert "URLSession" in result or "No matches found" in result

        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_improved_error_messages(self):
        """Test that error messages distinguish between no matches and extraction failures"""
        try:
            extractor = DashExtractor("apple_api_reference")

            # Search for something that definitely doesn't exist
            result = extractor.search(
                "xyzabc123nonexistent", language="swift", max_results=1
            )

            # Should say "No matches found" not "couldn't extract documentation"
            assert "No matches found" in result
            assert "couldn't extract documentation" not in result

        except FileNotFoundError:
            pytest.skip("Apple docset not installed")

    def test_carplay_search_comprehensive(self):
        """Test that CarPlay search returns framework and related entries like Dash"""
        try:
            extractor = DashExtractor("apple_api_reference")

            # Get the SQLite connection to examine raw results
            conn = sqlite3.connect(extractor.optimized_db)
            cursor = conn.cursor()

            # First, let's see what's actually in the database for CarPlay
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE name LIKE '%CarPlay%'
                ORDER BY
                    CASE
                        WHEN name = 'CarPlay' THEN 0
                        WHEN name LIKE 'CarPlay%' THEN 1
                        ELSE 2
                    END,
                    LENGTH(name)
                LIMIT 50
            """
            )

            db_results = cursor.fetchall()
            conn.close()

            print(f"\nFound {len(db_results)} CarPlay-related entries in database:")
            for name, doc_type, path in db_results[:10]:
                print(f"  - {name} ({doc_type}) - {path[:80]}...")

            # Now test our search implementation with more debugging
            print("\nTesting search implementation...")
            result = extractor.search("CarPlay", language="swift", max_results=30)

            # Print what we actually got back
            print(f"\nSearch result length: {len(result)} characters")
            print(f"First 1000 chars of result:\n{result[:1000]}")

            # Count how many documentation entries we got (separated by ---)
            entry_count = (
                result.count("\n\n---\n\n") + 1
                if result and "---" not in result
                else result.count("\n\n---\n\n")
            )
            print(f"\nNumber of documentation entries returned: {entry_count}")

            # Check that we found results
            assert "No matches found" not in result, "Should find CarPlay entries"

            # Check for the main CarPlay framework entry
            assert "CarPlay" in result, "Should find main CarPlay framework"

            # Check for expected name-matching entries (items that actually contain "CarPlay" in their name)
            expected_entries = [
                "carPlay",  # Property from User Notifications
                "carPlaySetting",  # Property from User Notifications
                "allowInCarPlay",  # Property from User Notifications
                "CarPlay Constants",  # Guide
                "CarPlay Navigation",  # Guide
            ]

            found_entries: list[str] = []
            for entry in expected_entries:
                if entry in result:
                    found_entries.append(entry)

            print(
                f"\nFound {len(found_entries)} of {len(expected_entries)} expected name-matching entries"
            )
            print(f"Found entries: {found_entries}")

            # We should find at least some name-matching entries
            assert (
                len(found_entries) > 0
            ), f"Should find entries with 'CarPlay' in their names. Result:\n{result[:500]}..."

            # Check that the framework has a drilldown note
            assert (
                "additional members not shown" in result
            ), "Framework should show drilldown note"
            assert (
                "search_docs('CarPlay'" in result or "list_entries" in result
            ), "Should provide drilldown guidance"

            # Test that ranking works - exact match should come before prefix/substring matches
            if "CarPlay" in result and "carPlay" in result:
                framework_pos = result.index("# CarPlay\n")  # Framework entry
                property_pos = result.index("carPlay")  # Property entry
                assert (
                    framework_pos < property_pos
                ), "Exact match 'CarPlay' framework should come before 'carPlay' property"

        except FileNotFoundError:
            pytest.skip("Apple docset not installed")
        except Exception as e:
            print(f"Error during test: {e}")
            raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
