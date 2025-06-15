#!/usr/bin/env python3
"""
Validation script to test all available cheatsheets on the local system.
This is an integration test that validates the extraction code works with
all real cheatsheet files installed in Dash.

Usage: python scripts/validate_cheatsheets.py
"""

import sys
import os

# Suppress loading messages during import
_original_stdout = sys.stdout
_original_stderr = sys.stderr
sys.stdout = open(os.devnull, "w")
sys.stderr = open(os.devnull, "w")

from docsetmcp.server import (
    list_available_cheatsheets,
    list_cheatsheet_categories,
    search_cheatsheet,
    CheatsheetExtractor,
)

# Restore stdout/stderr
sys.stdout.close()
sys.stderr.close()
sys.stdout = _original_stdout
sys.stderr = _original_stderr


def test_cheatsheet(name: str) -> bool:
    """Test a single cheatsheet"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print("=" * 60)

    try:
        # Test 1: Can we create the extractor?
        extractor = CheatsheetExtractor(name)
        print("✓ Extractor created successfully")

        # Test 2: Can we get categories?
        categories = extractor.get_categories()
        print(
            f"✓ Found {len(categories)} categories: {', '.join(categories[:5])}{' ...' if len(categories) > 5 else ''}"
        )

        # Test 3: Can we get full content?
        full_content = search_cheatsheet(name)
        lines = full_content.split("\n")
        non_empty_lines = [l for l in lines if l.strip()]
        print(
            f"✓ Full content extracted: {len(lines)} lines, {len(non_empty_lines)} non-empty"
        )

        # Test 4: Can we extract a category? (test first category if available)
        if categories:
            cat_content = search_cheatsheet(name, category=categories[0])
            cat_lines = cat_content.split("\n")
            cat_non_empty = [l for l in cat_lines if l.strip()]
            print(
                f"✓ Category '{categories[0]}' extracted: {len(cat_lines)} lines, {len(cat_non_empty)} non-empty"
            )

            # Check if we got actual content (not just headers)
            has_code = "```" in cat_content
            has_commands = any(
                "##" in line for line in cat_lines[2:]
            )  # Skip title lines
            if has_code or has_commands:
                print(
                    f"  → Contains {'code blocks' if has_code else ''}{' and ' if has_code and has_commands else ''}{'commands' if has_commands else ''}"
                )
            else:
                print(f"  ⚠ No code blocks or commands found in category")

        return True

    except Exception as e:
        print(f"✗ ERROR: {str(e)}")
        return False


def main() -> None:
    # Get list of all cheatsheets
    result = list_available_cheatsheets()

    # Parse the cheatsheet names
    cheatsheets: list[str] = []
    for line in result.split("\n"):
        if line.startswith("- **"):
            # Extract the simplified name
            parts = line.split("**")
            if len(parts) >= 3:
                simple_name = parts[1]
                cheatsheets.append(simple_name)

    print(f"Found {len(cheatsheets)} cheatsheets to test")

    # Test each cheatsheet
    success_count = 0
    failed: list[str] = []

    for cs in cheatsheets:
        if test_cheatsheet(cs):
            success_count += 1
        else:
            failed.append(cs)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"Total cheatsheets: {len(cheatsheets)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(failed)}")

    if failed:
        print(f"\nFailed cheatsheets:")
        for f in failed:
            print(f"  - {f}")

    # Test a few specific ones in detail
    print(f"\n{'='*60}")
    print("DETAILED TEST SAMPLES")
    print("=" * 60)

    test_samples = ["git", "vim", "docker", "http-status-codes", "regular-expressions"]

    for sample in test_samples:
        if sample in cheatsheets:
            print(f"\n--- {sample.upper()} ---")
            try:
                # Get categories
                categories = list_cheatsheet_categories(sample)
                print("Categories:")
                for line in categories.split("\n")[2:-2]:  # Skip header and footer
                    print(f"  {line}")

                # Get first few lines of content
                content = search_cheatsheet(sample)
                lines = content.split("\n")[:10]
                print("\nFirst 10 lines of content:")
                for line in lines:
                    print(f"  {line}")

            except Exception as e:
                print(f"  Error: {e}")


if __name__ == "__main__":
    main()
