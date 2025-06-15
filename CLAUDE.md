# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that provides access to local documentation in the Dash docset format. The primary purpose is to search and extract documentation from installed docsets and cheatsheets for quick, offline reference.

## Architecture

The codebase follows a modular architecture:

- **docsetmcp/server.py**: Main MCP server implementation using FastMCP. Contains the DashExtractor class that handles:
  - Apple cache format (SHA-1 UUID-based with brotli compression)
  - Tarix format (tar.gz archives)
  - SQLite database queries for documentation lookup
  - HTML to Markdown conversion

- **docsetmcp/config_loader.py**: Configuration system that loads YAML configs for 165+ supported docsets. Provides smart defaults and handles both simple and complex configuration formats.

- **docsetmcp/docsets/**: YAML configuration files for each supported docset, defining:
  - Docset paths and formats
  - Language variants and filters
  - Type priorities for search results

## Development Commands

### Setup

```bash
# Install in development mode
pip install -e .

# Install test dependencies
pip install pytest pytest-cov pytest-xdist

# Install all development dependencies
pip install -r requirements.txt

# Set up pre-commit hooks
pre-commit install
```

### Testing

```bash
# Run basic structure tests
pytest tests/test_docsets.py::TestDocsets::test_yaml_structure -v

# Run quick tests (structure + existence)
pytest tests/ -k "yaml_structure or test_docset_exists" -v

# Run full test suite (all docsets)
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=docsetmcp --cov-report=html -v

# Run tests in parallel
pytest tests/ -n auto -v
```

### Installation

```bash
# Build package
python setup.py sdist bdist_wheel

# Install from source
pip install .
```

### Code Formatting

```bash
# Format Python code with Black
black docsetmcp/

# Format YAML files with yamlfix
yamlfix docsetmcp/docsets/*.yaml

# Run all pre-commit hooks
pre-commit run --all-files

# Run specific hook
pre-commit run yamlfix --all-files
```

### Spell Checking

```bash
# Run spell check (cspell installed automatically during setup)
npm run spell
```

## Key Implementation Details

1. **Multi-Format Support**: The server detects and handles both Apple's modern cache format (using SHA-1 based UUIDs) and the older tarix compression format automatically based on docset configuration.

2. **Caching Strategy**: Extracted documentation is cached in memory (_fs_cache for Apple format, _html_cache for tarix) to improve performance on repeated queries.

3. **Search Algorithm**: Uses SQLite FTS (Full Text Search) on the optimizedIndex.dsidx database, with fallback to LIKE queries. Results are prioritized by type (Protocol > Class > Struct > etc).

4. **Configuration Loading**: The ConfigLoader applies smart defaults, allowing minimal YAML configs while supporting complex overrides when needed.

## MCP Tools Exposed

### Primary Tools - Documentation Docsets

- **list_languages**: Discover all programming languages with available documentation
- **list_docsets_by_language**: Find docsets for a specific programming language
- **search_docs**: Search and extract documentation with parameters for query, docset, language, and max_results
- **list_available_docsets**: List all configured and available docsets
- **list_frameworks**: List frameworks/types within a specific docset

### Secondary Tools - Cheatsheets

- **fetch_cheatsheet**: Fetch entire cheatsheet content (recommended for comprehensive access)
- **search_cheatsheet**: Search within cheatsheets for specific queries
- **list_available_cheatsheets**: List all available Dash cheatsheets
- **list_cheatsheet_categories**: List categories within a specific cheatsheet

## Best Practices

### Finding Documentation

1. **Start with language discovery**: Use `list_languages` to see what's available
2. **Find relevant docsets**: Use `list_docsets_by_language` to find documentation for your language
3. **Search within docsets**: Use `search_docs` with the appropriate docset parameter

Example workflow:

```txt
1. list_languages() → See "Python" is available
2. list_docsets_by_language("python") → Find "python3" docset
3. search_docs("asyncio", docset="python3")
```

### Working with Cheatsheets

For cheatsheets, **fetch_cheatsheet** is recommended as it provides complete access to all commands and examples.
