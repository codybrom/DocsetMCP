"""
Type definitions for docsetmcp
"""

from typing import TypedDict


# Configuration types
class LanguageConfig(TypedDict, total=False):
    """Language configuration with filter and prefix"""

    filter: str
    prefix: str


# Raw YAML config - use separate required/optional types to maintain type safety
class RequiredDocsetFields(TypedDict):
    """Required fields in docset YAML configuration"""

    name: str
    docset_path: str
    languages: list[str] | dict[str, str | LanguageConfig]


class OptionalDocsetFields(TypedDict, total=False):
    """Optional fields in docset YAML configuration"""

    description: str
    primary_language: str
    format: str
    enabled: bool
    framework_pattern: str
    types: dict[str, int] | list[str]


class DocsetConfig(RequiredDocsetFields, OptionalDocsetFields):
    """Complete docset configuration combining required and optional fields"""

    pass


class ProcessedLanguageConfig(TypedDict):
    """Language config with guaranteed fields after processing"""

    filter: str
    prefix: str


class ProcessedDocsetConfig(TypedDict):
    """Docset configuration after processing with all defaults applied"""

    # Required fields - always present after _apply_defaults
    name: str
    docset_path: str
    format: str
    enabled: bool
    framework_pattern: str
    languages: dict[str, ProcessedLanguageConfig]
    types: dict[str, int]
    # Optional fields
    description: str | None
    primary_language: str | None


class DefaultConfig(TypedDict):
    format: str
    enabled: bool
    framework_pattern: str
    language_defaults: ProcessedLanguageConfig


# Apple documentation types
class ContentItem(TypedDict, total=False):
    """Content item in Apple documentation"""

    type: str
    text: str
    code: str
    inlineContent: list["ContentItem"]
    identifier: str
    title: str


class ApplePlatform(TypedDict, total=False):
    """Apple platform information"""

    name: str
    introducedAt: str


class AppleMetadata(TypedDict, total=False):
    """Apple documentation metadata"""

    title: str
    role: str
    platforms: list[ApplePlatform]
    availability: list[str]


class AppleDiscussionSection(TypedDict, total=False):
    """Apple documentation discussion section"""

    kind: str
    content: list[ContentItem]


class AppleDocumentation(TypedDict, total=False):
    """Apple documentation structure from JSON"""

    metadata: AppleMetadata
    discussionSections: list[AppleDiscussionSection]


# API response types
class DocsetInfo(TypedDict):
    docset: str
    name: str
    languages: list[str]
    description: str | None
