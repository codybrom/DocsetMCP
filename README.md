# Unofficial Dash MCP Server

Search local documentation from Dash docsets through the Model Context Protocol (MCP).

## What is MCP?

MCP (Model Context Protocol) is a standard for connecting AI assistants to external tools and data sources. This allows Claude and other AI assistants to directly access documentation from your local Dash installation.

## Features

- **Multi-Docset Support**: Search Apple, NodeJS, Bash, C, Arduino, Font Awesome, and more
- **Cheatsheet Support**: Quick access to Git, Vim, Docker, and other cheatsheets
- **Direct Access**: Search documentation without leaving your conversation
- **Fast Lookups**: Efficient extraction from both Apple cache and tarix formats
- **Framework Discovery**: List all available frameworks/types in any docset
- **Smart Search**: Fuzzy matching for cheatsheet names

## Prerequisites

- macOS (Dash is Mac-only)
- [Dash](https://kapeli.com/dash) with desired docsets downloaded
- Python 3.8 or higher
- An AI assistant that supports MCP (Claude Desktop, Claude Code CLI, Cursor IDE, etc.)

## Installation

### Simple Installation (Recommended)

1. **Install from PyPI**:

   ```bash
   pip install dashmcp
   ```

2. **Configure your MCP client** (see configuration options below)

### Development Installation

1. **Clone and install**:

   ```bash
   git clone https://github.com/codybrom/dashmcp.git
   cd dashmcp
   pip install -e .
   ```

2. **Run tests** (optional):

   ```bash
   # Install test dependencies
   pip install pytest pytest-cov pytest-xdist
   
   # Run basic tests
   pytest tests/test_docsets.py::TestDocsets::test_yaml_structure -v
   
   # Run quick tests (structure + existence checks)
   pytest tests/ -k "yaml_structure or test_docset_exists" -v
   
   # Run full test suite (all docsets)
   pytest tests/ -v
   
   # Run with coverage
   pytest tests/ --cov=dashmcp --cov-report=html -v
   
   # Validate all local cheatsheets work (integration test)
   python scripts/validate_cheatsheets.py
   ```

## Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dash": {
      "command": "uvx",
      "args": ["dashmcp"]
    }
  }
}
```

Restart Claude Desktop.

### Claude Code CLI

```bash
claude mcp add dash "uvx dashmcp"

# Or for all projects
claude mcp add --scope user dash "uvx dashmcp"
```

### Cursor or other MCP Clients that use `mcp.json`

Add/Update `mcp.json` in your project root:

```json
{
  "mcpServers": {
    "dash": {
      "command": "uvx",
      "args": ["dashmcp"]
    }
  }
}
```

Restart Cursor and check Settings > MCP for connection status.

## Usage

Once configured in any MCP client, you can use these commands:

### Search Documentation

```txt
Use search_docs to find documentation for AppIntent
```

### List Available Docsets

```txt
Use list_available_docsets to see all loaded docsets
```

### Search Specific Docsets

```txt
Use search_docs with query "fs", docset "nodejs", language "javascript", and max_results 3
```

### Search Cheatsheets

```txt
Use search_cheatsheet with cheatsheet "git" to see all Git categories

Use search_cheatsheet with cheatsheet "git", query "branch" to find branch-related commands

Use list_available_cheatsheets to see all available cheatsheets
```

## How It Works

1. **Multi-Format Support**: Handles both Apple cache format and tarix compression
2. **Direct Database Access**: Queries Dash's SQLite databases for fast lookups
3. **Smart Extraction**: Decompresses Apple's DocC JSON or extracts HTML from tarix archives
4. **Markdown Formatting**: Converts documentation to readable Markdown

## Tools Available

### search_docs

Search and extract documentation from any docset.

**Parameters**:

- `query` (required): The API/function name to search for
- `docset` (optional): Docset to search in (default: "apple")
- `language` (optional): Programming language variant (varies by docset)
- `max_results` (optional): 1-10 results (default: 3)

### search_cheatsheet

Search a Dash cheatsheet for quick reference information.

**Parameters**:

- `cheatsheet` (required): Name of the cheatsheet (e.g., 'git', 'vim', 'docker')
- `query` (optional): Search query within the cheatsheet
- `category` (optional): Category to filter results
- `max_results` (optional): 1-50 results (default: 10)

### list_available_docsets

List all available Dash docsets that can be searched.

### list_available_cheatsheets

List all available Dash cheatsheets.

### list_frameworks

List available frameworks/types in a specific docset.

**Parameters**:

- `docset` (optional): Docset to list from (default: "apple")
- `filter` (optional): Filter framework/type names

## Troubleshooting

- **"Docset not found"**: Download the desired docset in Dash.app first
- **No results found**: The content might not be in your offline cache
- **MCP connection failed**: Check your MCP client logs and ensure the command path is correct

## Technical Details

The MCP server:

- Implements the MCP protocol for tool integration
- Supports both Apple cache format (SHA-1 UUID-based) and tarix compression
- Caches extracted documentation for performance
- Auto-detects available docsets on startup
- Handles multiple programming languages per docset

## Adding New Docset Support

To add support for a new docset, create a YAML configuration file in `dashmcp/config/docsets/`:

### Simple Configuration

For most docsets using standard tarix format:

```yaml
# dashmcp/config/docsets/my_docset.yaml
name: My Docset
docset_name: My_Docset
docset_path: My_Docset.docset
languages:
 - python
 - javascript
types:
  - Class
  - Function
  - Module
  - Variable
```

### Advanced Configuration

For docsets with special requirements:

```yaml
# dashmcp/config/docsets/complex_docset.yaml
name: Complex Docset
docset_name: Complex_Docset
docset_path: Complex_Docset.docset
format: apple  # or "tarix" (default)
languages:
  swift:
    filter: "swift/"
    prefix: "Swift."
  objc:
    filter: "objc/"
    prefix: ""
types:
  Protocol: 0
  Class: 1
  Struct: 2
  Function: 3
framework_path_pattern: "documentation/(.*?)/"
framework_path_extract: 1
```

### Configuration Fields

- **name**: Display name for the docset
- **docset_name**: Exact folder name in Dash's DocSets directory
- **docset_path**: Path to the .docset bundle
- **languages**: List of supported languages (simple) or dict with filters/prefixes (advanced)
- **types**: List of documentation types in priority order (simple) or dict with priority values (advanced)
- **format**: "tarix" (default) or "apple" for Apple's cache format
- **framework_path_pattern**: Regex to extract framework names from paths
- **framework_path_extract**: Regex group number to extract

The ConfigLoader automatically applies smart defaults, so you only need to specify non-default values.

## License

MIT License - Feel free to modify and extend\!
