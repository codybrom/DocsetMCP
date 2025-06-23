#!/usr/bin/env python3
"""
Configuration loader with smart defaults for dash-mcp
"""

import yaml
import sqlite3
import os
from pathlib import Path

from .types import (
    LanguageConfig,
    DocsetConfig,
    ProcessedDocsetConfig,
    ProcessedLanguageConfig,
    DefaultConfig,
)


class ConfigLoader:
    """Load and process docset configurations with smart defaults"""

    # Default values applied to all configs
    DEFAULTS: DefaultConfig = {
        "format": "tarix",
        "enabled": True,
        "framework_pattern": "",
        "language_defaults": {"filter": "", "prefix": ""},
    }

    def __init__(self, config_dir: Path | None = None):
        if config_dir is None:
            config_dir = Path(__file__).parent / "docsets"
        self.config_dir = config_dir

    def load_config(self, docset_name: str) -> ProcessedDocsetConfig:
        """Load a single docset configuration with defaults applied"""
        config_file = self.config_dir / f"{docset_name}.yaml"

        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")

        with open(config_file, "r") as f:
            raw_config = yaml.safe_load(f)

        return self._apply_defaults(raw_config)

    def load_all_configs(
        self, additional_docset_paths: list[str] | None = None
    ) -> dict[str, ProcessedDocsetConfig]:
        """Load all docset configurations, including auto-detected ones"""
        configs: dict[str, ProcessedDocsetConfig] = {}

        # Load existing YAML configs
        for config_file in self.config_dir.glob("*.yaml"):
            docset_name = config_file.stem
            try:
                configs[docset_name] = self.load_config(docset_name)
            except Exception as e:
                print(f"Warning: Failed to load {docset_name}: {e}")

        # Auto-detect docsets in additional paths
        if additional_docset_paths:
            auto_detected = self._discover_docsets(additional_docset_paths)
            # Only add auto-detected if they don't have explicit configs
            for docset_name, config in auto_detected.items():
                if docset_name not in configs:
                    configs[docset_name] = config

        return configs

    def _discover_docsets(
        self, search_paths: list[str]
    ) -> dict[str, ProcessedDocsetConfig]:
        """Discover and auto-configure docsets in the given paths"""
        discovered: dict[str, ProcessedDocsetConfig] = {}

        for search_path in search_paths:
            path = Path(os.path.expanduser(search_path))
            if not path.exists():
                continue

            # Look for .docset directories
            for docset_path in path.glob("*.docset"):
                docset_name = (
                    docset_path.stem.lower().replace(".", "").replace("-", "_")
                )

                # Skip if we already found this docset
                if docset_name in discovered:
                    continue

                try:
                    config = self._generate_config_from_docset(docset_path)
                    if config:
                        discovered[docset_name] = config
                except Exception as e:
                    print(f"Warning: Failed to auto-detect {docset_path.name}: {e}")

        return discovered

    def _generate_config_from_docset(
        self, docset_path: Path
    ) -> ProcessedDocsetConfig | None:
        """Generate a configuration by analyzing a docset"""
        # Check if it's a valid docset structure
        resources = docset_path / "Contents" / "Resources"
        if not resources.exists():
            return None

        # Look for database files to determine format
        optimized_db = resources / "optimizedIndex.dsidx"
        docset_db = resources / "docSet.dsidx"
        tarix_file = resources / "tarix.tgz"

        # Determine format and database path
        if tarix_file.exists() and optimized_db.exists():
            db_path = optimized_db
        elif docset_db.exists():
            db_path = docset_db
        else:
            return None

        # Extract info from database
        name = docset_path.stem
        docset_info = self._analyze_docset_database(db_path)

        # Create config
        raw_config: DocsetConfig = {
            "name": name,
            "docset_path": docset_path.name,
            "description": f"Auto-detected {name} documentation",
            "languages": docset_info.get(
                "languages", ["javascript"]
            ),  # Default fallback
            "types": docset_info.get("types", []),
        }

        return self._apply_defaults(raw_config)

    def _analyze_docset_database(self, db_path: Path) -> dict[str, list[str]]:
        """Analyze docset database to extract types and infer languages"""
        info: dict[str, list[str]] = {"types": [], "languages": []}

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get distinct types
            cursor.execute(
                "SELECT DISTINCT type FROM searchIndex WHERE type IS NOT NULL"
            )
            types = [row[0] for row in cursor.fetchall()]
            info["types"] = types

            # Infer languages based on common patterns
            languages: set[str] = set()

            # Sample some entries to look for language clues
            cursor.execute("SELECT name, type FROM searchIndex LIMIT 100")
            entries = cursor.fetchall()

            # Look for language-specific patterns
            for name, _ in entries:
                name_lower = name.lower()

                # JavaScript/TypeScript patterns
                if any(
                    pattern in name_lower
                    for pattern in [
                        "js",
                        "javascript",
                        "node",
                        "npm",
                        "react",
                        "vue",
                        "angular",
                    ]
                ):
                    languages.add("javascript")
                if any(pattern in name_lower for pattern in ["ts", "typescript"]):
                    languages.add("typescript")

                # Python patterns
                if any(
                    pattern in name_lower
                    for pattern in [
                        "python",
                        "py",
                        "django",
                        "flask",
                        "pandas",
                        "numpy",
                    ]
                ):
                    languages.add("python")

                # Other common languages
                if any(
                    pattern in name_lower for pattern in ["java", "spring", "android"]
                ):
                    languages.add("java")
                if any(
                    pattern in name_lower
                    for pattern in ["swift", "ios", "macos", "cocoa"]
                ):
                    languages.add("swift")
                if any(
                    pattern in name_lower for pattern in ["php", "laravel", "symfony"]
                ):
                    languages.add("php")

            # Default to common web languages if nothing detected
            if not languages:
                languages = {"javascript", "typescript"}

            info["languages"] = list(languages)

            conn.close()

        except Exception as e:
            print(f"Warning: Could not analyze database {db_path}: {e}")
            # Provide sensible defaults
            info = {
                "types": ["Guide", "Method", "Class"],
                "languages": ["javascript", "typescript"],
            }

        return info

    def _apply_defaults(self, config: DocsetConfig) -> ProcessedDocsetConfig:
        """Apply default values to a configuration"""
        # Process languages (required field)
        languages = self._process_languages(config["languages"])

        # Process types
        types_raw = config.get("types") or []
        types = self._process_types(types_raw)

        # Build result with all required fields
        result: ProcessedDocsetConfig = {
            "name": config["name"],
            "docset_path": config["docset_path"],
            "format": config.get("format", self.DEFAULTS["format"]),
            "enabled": config.get("enabled", self.DEFAULTS["enabled"]),
            "framework_pattern": config.get(
                "framework_pattern", self.DEFAULTS["framework_pattern"]
            ),
            "languages": languages,
            "types": types,
            "description": config.get("description"),
            "primary_language": config.get("primary_language"),
        }

        return result

    def _process_languages(
        self, languages: list[str] | dict[str, str | LanguageConfig]
    ) -> dict[str, ProcessedLanguageConfig]:
        """Process language configuration, applying defaults for simple syntax"""
        if isinstance(languages, list):
            # Simple syntax: languages: ["python", "javascript"]
            result: dict[str, ProcessedLanguageConfig] = {}
            for lang in languages:
                result[lang] = ProcessedLanguageConfig(
                    filter=self.DEFAULTS["language_defaults"]["filter"],
                    prefix=self.DEFAULTS["language_defaults"]["prefix"],
                )
            return result

        else:
            # Must be dict at this point due to type annotation
            # Full syntax: preserve existing structure but apply defaults
            processed_result: dict[str, ProcessedLanguageConfig] = {}
            # languages is already dict[str, Any] in this branch
            for lang, lang_config in languages.items():
                if isinstance(lang_config, dict):
                    # Full config provided
                    processed_result[lang] = ProcessedLanguageConfig(
                        filter=lang_config.get(
                            "filter", self.DEFAULTS["language_defaults"]["filter"]
                        ),
                        prefix=lang_config.get(
                            "prefix", self.DEFAULTS["language_defaults"]["prefix"]
                        ),
                    )
                else:
                    # Simple string or other format
                    processed_result[lang] = ProcessedLanguageConfig(
                        filter=self.DEFAULTS["language_defaults"]["filter"],
                        prefix=self.DEFAULTS["language_defaults"]["prefix"],
                    )
            return processed_result

    def _process_types(self, types: dict[str, int] | list[str]) -> dict[str, int]:
        """Process types configuration, supporting both dict and array formats"""
        if isinstance(types, list):
            # Array format: convert to numbered dict with 0-based indexing
            result = {type_name: index for index, type_name in enumerate(types)}
        else:
            # Must be dict at this point due to type annotation
            # Dict format: use as-is
            result = types.copy()

        # Automatically add 'default' with next available number if not present
        if "default" not in result:
            max_priority = max(result.values()) if result else -1
            result["default"] = max_priority + 1

        return result


def create_simplified_config(
    name: str,
    docset_path: str,
    languages: list[str],
    types: dict[str, int],
    **overrides: str | bool,
) -> DocsetConfig:
    """Helper function to create a simplified config"""
    # Start with required fields
    config: dict[str, str | list[str] | dict[str, int] | bool] = {
        "name": name,
        "docset_path": docset_path,
        "languages": languages,
        "types": types,
    }

    # Add any overrides (for complex cases)
    for key, value in overrides.items():
        if key in {
            "description",
            "primary_language",
            "format",
            "framework_pattern",
            "enabled",
        }:
            config[key] = value

    # Cast to DocsetConfig - this is safe because we've set all required fields
    return config  # type: ignore[return-value]


if __name__ == "__main__":
    # Test the config loader
    loader = ConfigLoader()

    # Test loading a specific config
    try:
        config = loader.load_config("nodejs")
        print("NodeJS config:")
        print(yaml.dump(config, default_flow_style=False))
    except Exception as e:
        print(f"Error: {e}")

    # Count total configs
    all_configs = loader.load_all_configs()
    print(f"\nLoaded {len(all_configs)} configurations successfully")
