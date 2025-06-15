#!/usr/bin/env python3
"""
Configuration loader with smart defaults for dash-mcp
"""

import yaml
from pathlib import Path
from typing import Dict, Any, List, Union, Optional


class ConfigLoader:
    """Load and process docset configurations with smart defaults"""

    # Default values applied to all configs
    DEFAULTS = {
        "format": "tarix",
        "enabled": True,
        "framework_path_pattern": "",
        "framework_path_extract": None,
        "language_defaults": {"filter": "", "prefix": ""},
    }

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent / "config" / "docsets"
        self.config_dir = config_dir

    def load_config(self, docset_name: str) -> Dict[str, Any]:
        """Load a single docset configuration with defaults applied"""
        config_file = self.config_dir / f"{docset_name}.yaml"

        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")

        with open(config_file, "r") as f:
            raw_config = yaml.safe_load(f)

        return self._apply_defaults(raw_config)

    def load_all_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load all docset configurations"""
        configs = {}

        for config_file in self.config_dir.glob("*.yaml"):
            docset_name = config_file.stem
            try:
                configs[docset_name] = self.load_config(docset_name)
            except Exception as e:
                print(f"Warning: Failed to load {docset_name}: {e}")

        return configs

    def _apply_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply default values to a configuration"""
        # Start with defaults
        result = {
            "format": self.DEFAULTS["format"],
            "enabled": self.DEFAULTS["enabled"],
            "framework_path_pattern": self.DEFAULTS["framework_path_pattern"],
            "framework_path_extract": self.DEFAULTS["framework_path_extract"],
        }

        # Override with provided values
        for key, value in config.items():
            if key == "languages":
                result[key] = self._process_languages(value)
            elif key == "types" or key == "type_priority":
                result["types"] = self._process_types(value)
            else:
                result[key] = value

        return result

    def _process_languages(
        self, languages: Union[List[str], Dict[str, Any]]
    ) -> Dict[str, Dict[str, str]]:
        """Process language configuration, applying defaults for simple syntax"""
        if isinstance(languages, list):
            # Simple syntax: languages: ["python", "javascript"]
            result = {}
            for lang in languages:
                result[lang] = self.DEFAULTS["language_defaults"].copy()
            return result

        elif isinstance(languages, dict):
            # Full syntax: preserve existing structure but apply defaults
            result = {}
            for lang, lang_config in languages.items():
                if isinstance(lang_config, dict):
                    # Full config provided
                    result[lang] = {
                        "filter": lang_config.get(
                            "filter", self.DEFAULTS["language_defaults"]["filter"]
                        ),
                        "prefix": lang_config.get(
                            "prefix", self.DEFAULTS["language_defaults"]["prefix"]
                        ),
                    }
                else:
                    # Simple string or other format
                    result[lang] = self.DEFAULTS["language_defaults"].copy()
            return result

        else:
            raise ValueError(f"Invalid languages format: {type(languages)}")

    def _process_types(self, types: Union[Dict[str, int], List[str]]) -> Dict[str, int]:
        """Process types configuration, supporting both dict and array formats"""
        if isinstance(types, list):
            # Array format: convert to numbered dict with 0-based indexing
            result = {type_name: index for index, type_name in enumerate(types)}
        elif isinstance(types, dict):
            # Dict format: use as-is
            result = types.copy()
        else:
            raise ValueError(f"Invalid types format: {type(types)}")

        # Automatically add 'default' with next available number if not present
        if "default" not in result:
            max_priority = max(result.values()) if result else -1
            result["default"] = max_priority + 1

        return result


def create_simplified_config(
    name: str,
    docset_name: str,
    docset_path: str,
    languages: List[str],
    types: Dict[str, int],
    **overrides,
) -> Dict[str, Any]:
    """Helper function to create a simplified config"""
    config = {
        "name": name,
        "docset_name": docset_name,
        "docset_path": docset_path,
        "languages": languages,
        "types": types,
    }

    # Add any overrides (for complex cases)
    config.update(overrides)

    return config


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
