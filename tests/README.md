# Test Suite for dashmcp

This directory contains comprehensive tests for dashmcp.

## Test Structure

- `test_docsets.py` - Main test suite for docset configurations
- `helpers.py` - Test utilities and helper classes
- `conftest.py` - pytest configuration
- `__init__.py` - Test package marker

## Test Categories

### TestDocsets

Tests all docset configurations (165 total):

- **test_docset_exists** - Verifies each configured docset exists on disk
- **test_docset_search** - Tests search functionality for each docset
- **test_docset_types** - Validates all configured types exist in the database
- **test_yaml_structure** - Checks YAML file structure and required fields
- **test_no_duplicate_names** - Ensures no duplicate docset names
- **test_server_initialization** - Basic server initialization test

### TestDocsetContent

Tests actual content extraction:

- **test_apple_documentation** - Apple API reference extraction
- **test_nodejs_documentation** - Node.js documentation extraction  
- **test_python_documentation** - Python documentation extraction

### TestEdgeCases

Tests error handling and edge cases:

- **test_nonexistent_docset** - Non-existent docset handling
- **test_empty_search_query** - Empty query handling
- **test_special_characters_in_search** - Special character handling

## Running Tests

```bash
# Basic tests
python run_tests.py

# Quick tests (structure + existence)
python run_tests.py --quick

# Full test suite (all docsets)
python run_tests.py --full

# With coverage
python run_tests.py --coverage
```

## Test Results

All 165 configured docsets pass comprehensive testing:

- ✅ Docset existence verification
- ✅ Search functionality
- ✅ Type validation
- ✅ YAML structure validation
- ✅ Server integration

The test suite validates that every configured docset type has actual entries in the SQLite database and that search queries return results.
