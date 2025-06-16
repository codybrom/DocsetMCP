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

3. **Search Algorithm**: Uses SQLite case-insensitive LIKE queries on the optimizedIndex.dsidx database. Results are ranked by match type (exact > prefix > substring) and then by dynamic type ordering from docset configuration files. Only returns entries where the search term matches the item name.

4. **Configuration Loading**: The ConfigLoader applies smart defaults, allowing minimal YAML configs while supporting complex overrides when needed.

5. **Container Type Detection**: Framework, class, and module entries automatically include drilldown notes when they contain additional members, guiding users to search for more specific content.

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

Example workflows:

**Python Example:**

```txt
1. list_languages() → See "Python" is available
2. list_docsets_by_language("python") → Find "python3" docset
3. search_docs("asyncio", docset="python3")
```

**Apple API Framework Discovery:**

```txt
1. search_docs("CarPlay", docset="apple_api_reference", language="swift") → Find CarPlay framework + related entries
2. Follow drilldown note: search_docs("CarPlay", language="swift", max_results=50) → See all CarPlay members
3. search_docs("CPListTemplate", docset="apple_api_reference", language="swift") → Specific class
```

**Apple API Class Discovery:**

```txt
1. search_docs("SwiftData", docset="apple_api_reference", language="swift") → Framework overview
2. search_docs("ModelContext", docset="apple_api_reference", language="swift") → Specific class
3. search_docs("Query", docset="apple_api_reference", language="swift") → Another class
```

### Working with Cheatsheets

For cheatsheets, **fetch_cheatsheet** is recommended as it provides complete access to all commands and examples.

## Apple Documentation Search Behavior

Apple API documentation has been optimized for intuitive searching:

### How Apple Documentation Search Works

1. **Name-Based Matching**: Search only returns entries where the search term matches the item name (exact, prefix, or substring matches).

2. **Framework Discovery**: Searching for framework names like "CarPlay" or "SwiftData" returns:
   - The main framework entry with overview documentation
   - Related entries that contain the framework name (properties, guides, etc.)
   - Drilldown notes showing how to explore framework members

3. **Smart Ranking**: Results are ordered by:
   - Exact matches first ("CarPlay" framework for "CarPlay" search)
   - Prefix matches second ("carPlay" property for "CarPlay" search)
   - Substring matches last ("allowInCarPlay" for "CarPlay" search)
   - Type priority from configuration (Framework > Class > Protocol > etc.)

4. **Container Type Guidance**: Framework, class, and module entries automatically include notes like:

   ```md
   **Note:** The CarPlay framework contains 42 additional members not shown.
   Use `search_docs('CarPlay', language='swift', max_results=50)` to see all CarPlay members.
   ```

### Effective Apple Documentation Queries

**Framework-Level Searches** (returns framework + related entries):

- `search_docs("CarPlay", docset="apple_api_reference", language="swift")`
- `search_docs("SwiftData", docset="apple_api_reference", language="swift")`
- `search_docs("SwiftUI", docset="apple_api_reference", language="swift")`

**Class-Level Searches** (returns specific classes):

- `search_docs("UIImage", docset="apple_api_reference", language="swift")`
- `search_docs("ModelContext", docset="apple_api_reference", language="swift")`
- `search_docs("CPListTemplate", docset="apple_api_reference", language="swift")`

**Property/Method Searches** (returns specific APIs):

- `search_docs("viewDidLoad", docset="apple_api_reference", language="swift")`
- `search_docs("dataSource", docset="apple_api_reference", language="swift")`

### Language Parameter Guidelines

- **Always specify language**: `language="swift"` or `language="objc"`
- **Swift is recommended** for modern iOS/macOS development
- **Objective-C** for legacy code or specific Foundation APIs

### Apple Documentation Requirements

- Documentation must be cached locally in your Dash app
- Framework entries require the full docset to be downloaded
- Some newer APIs may not be available in offline cache

## Troubleshooting

### Common Issues and Solutions

1. **"Found entries but couldn't extract documentation"**
   - **Cause**: The documentation isn't cached locally
   - **Solution**: Open Dash app and download/update the docset

2. **"No matches found" for known Apple APIs**
   - **Cause**: Docset not installed or language mismatch
   - **Solution**: Check `list_available_docsets()` and ensure correct `language` parameter

3. **Too many results to browse**
   - **Cause**: Generic search terms return many matches
   - **Solution**: Use more specific terms or follow drilldown notes from framework entries

4. **Missing framework members**
   - **Cause**: Search only returns name matches, not all framework contents
   - **Solution**: Look for drilldown notes in framework entries, or increase `max_results`

5. **Wrong language results**
   - **Cause**: Default language may not match your needs
   - **Solution**: Always specify `language="swift"` or `language="objc"`

### Debug Commands

```bash
# Check if docset is available
list_available_docsets()

# Test framework-level search
search_docs("CarPlay", docset="apple_api_reference", language="swift")

# Test class-level search
search_docs("UIViewController", docset="apple_api_reference", language="swift")

# Find frameworks containing a keyword
list_frameworks("apple_api_reference", filter="YourKeyword")

# Get more results from a framework
search_docs("SwiftData", docset="apple_api_reference", language="swift", max_results=50)
```
