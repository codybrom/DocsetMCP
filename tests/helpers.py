#!/usr/bin/env python3
"""
Test helpers for docsetmcp
"""

import os
import sqlite3
from pathlib import Path


# Import the actual config type from shared types
from docsetmcp.types import ProcessedDocsetConfig


class TestDashExtractor:
    """Modified DashExtractor for testing individual configurations"""

    def __init__(self, docset_folder: str, config: ProcessedDocsetConfig):
        """Initialize with a specific configuration dictionary"""
        self.config = config

        # Default Dash docset location on macOS
        dash_docsets_path = os.path.expanduser(
            "~/Library/Application Support/Dash/DocSets"
        )
        self.docset = (
            Path(dash_docsets_path) / docset_folder / self.config["docset_path"]
        )

        # Set up paths based on docset format
        if self.config["format"] == "apple":
            self.fs_dir = self.docset / "Contents/Resources/Documents/fs"
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.cache_db = self.docset / "Contents/Resources/Documents/cache.db"
            self._fs_cache = {}
        elif self.config["format"] == "tarix":
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.tarix_archive = self.docset / "Contents/Resources/tarix.tgz"
            self.tarix_index = self.docset / "Contents/Resources/tarixIndex.db"
            self._html_cache = {}

        # Check if Dash docset exists
        if not self.docset.exists():
            raise FileNotFoundError(f"{self.config['name']} not found at {self.docset}")

    def search(
        self, query: str, language: str | None = None, limit: int = 10
    ) -> list[dict[str, str]]:
        """Search for documentation"""
        results: list[dict[str, str]] = []

        # Use first language if not specified
        if language is None and self.config.get("languages"):
            language = list(self.config["languages"].keys())[0]

        # Search the optimized index
        conn = sqlite3.connect(self.optimized_db)
        cursor = conn.cursor()

        # Get language filter if available
        lang_filter = ""
        if language and language in self.config.get("languages", {}):
            lang_config = self.config["languages"][language]
            lang_filter = lang_config.get("filter", "")

        # Build query based on whether we have a language filter
        if lang_filter:
            # Exact match first with language filter
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE name = ? AND path LIKE ?
                LIMIT ?
                """,
                (query, f"%{lang_filter}%", limit),
            )
        else:
            # Exact match without language filter
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE name = ?
                LIMIT ?
                """,
                (query, limit),
            )

        db_results = cursor.fetchall()

        if not db_results:
            # Try partial match
            if lang_filter:
                cursor.execute(
                    """
                    SELECT name, type, path
                    FROM searchIndex
                    WHERE name LIKE ? AND path LIKE ?
                    LIMIT ?
                    """,
                    (f"%{query}%", f"%{lang_filter}%", limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT name, type, path
                    FROM searchIndex
                    WHERE name LIKE ?
                    LIMIT ?
                    """,
                    (f"%{query}%", limit),
                )
            db_results = cursor.fetchall()

        conn.close()

        # Format results
        for name, entry_type, path in db_results:
            results.append({"name": name, "type": entry_type, "path": path})

        return results
