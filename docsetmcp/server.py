#!/usr/bin/env python3
"""
Dash MCP Server - Extract documentation from Dash docsets as Markdown
"""

import os
import sqlite3
import brotli
import hashlib
import base64
import tarfile
from pathlib import Path
from typing import Union, TypedDict, Optional

# MCP SDK imports
from mcp.server.fastmcp import FastMCP

# Import shared types
try:
    from .types import (
        ContentItem,
        AppleDocumentation,
        ProcessedDocsetConfig,
        DocsetInfo,
    )
except ImportError:
    from docsetmcp.types import (
        ContentItem,
        AppleDocumentation,
        ProcessedDocsetConfig,
        DocsetInfo,
    )


class MatchedDocsetInfo(TypedDict):
    config: ProcessedDocsetConfig
    matched_lang: Optional[str]


# Create MCP server
mcp = FastMCP("Dash")


class DashExtractor:
    config: ProcessedDocsetConfig

    def __init__(self, docset_type: str, docsets_base_path: str | None = None):
        # Load docset configuration using new config loader
        try:
            from .config_loader import ConfigLoader
        except ImportError:
            from docsetmcp.config_loader import ConfigLoader

        loader = ConfigLoader()

        try:
            self.config = loader.load_config(docset_type)
        except FileNotFoundError:
            raise ValueError(f"Unsupported docset type: {docset_type}")

        # Build list of paths to search for docsets
        search_paths: list[str] = []

        # Use custom docset location if provided, otherwise use configured paths
        if docsets_base_path:
            search_paths.append(os.path.expanduser(docsets_base_path))
        else:
            # Check environment variable for custom location
            env_path = os.getenv("DOCSET_PATH")
            if env_path:
                search_paths.append(os.path.expanduser(env_path))

            # Add additional paths from global config
            if docsetmcp_config.additional_docset_paths:
                additional_paths = docsetmcp_config.parse_path_list(
                    docsetmcp_config.additional_docset_paths
                )
                search_paths.extend(additional_paths)

            # If no custom paths specified, use default Dash location
            if not search_paths:
                search_paths.append(
                    os.path.expanduser("~/Library/Application Support/Dash/DocSets")
                )

        # Find the docset in the search paths
        self.docset: Path | None = None
        for search_path in search_paths:
            potential_docset = Path(search_path) / self.config["docset_path"]
            if potential_docset.exists():
                self.docset = potential_docset
                break

        # If not found, default to first search path for error reporting
        if self.docset is None:
            self.docset = Path(search_paths[0]) / self.config["docset_path"]
        # Set up paths based on docset format
        if self.config["format"] == "apple":
            self.fs_dir = self.docset / "Contents/Resources/Documents/fs"
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.cache_db = self.docset / "Contents/Resources/Documents/cache.db"
            # Cache for decompressed fs files
            self.fs_cache: dict[int, bytes] = {}
        elif self.config["format"] == "tarix":
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.tarix_archive = self.docset / "Contents/Resources/tarix.tgz"
            self.tarix_index = self.docset / "Contents/Resources/tarixIndex.db"
            # Cache for extracted HTML content
            self.html_cache: dict[str, str] = {}

        # Check if docset exists
        if not self.docset.exists():
            raise FileNotFoundError(
                f"{self.config['name']} docset not found at {self.docset}. "
                "Please ensure the docset is available at the configured location."
            )

    def _normalize_query(self, query: str) -> list[str]:
        """Normalize query for better matching"""
        # Remove extra spaces and convert to consistent format
        normalized = " ".join(query.split())
        # Also create a no-space version for cases like "App Intent" -> "AppIntent"
        no_spaces = normalized.replace(" ", "")
        # Return unique variations
        variations = [query]
        if normalized != query:
            variations.append(normalized)
        if no_spaces != query and no_spaces != normalized:
            variations.append(no_spaces)
        return variations

    def _get_type_order_clause(self) -> str:
        """Generate SQL CASE clause for type ordering based on config"""
        if "types" not in self.config or not self.config["types"]:
            return "0"  # No ordering if types not configured

        case_parts = ["CASE type"]
        # types is a dict mapping type_name -> priority_index
        for type_name, priority in self.config["types"].items():
            case_parts.append(f"    WHEN '{type_name}' THEN {priority}")
        case_parts.append(f"    ELSE {len(self.config['types'])}")
        case_parts.append("END")
        return "\n".join(case_parts)

    def search(self, query: str, language: str = "swift", max_results: int = 3) -> str:
        """Search for Apple API documentation"""
        results: list[str] = []

        # Search the optimized index
        conn = sqlite3.connect(self.optimized_db)
        cursor = conn.cursor()

        # Filter by language using config
        if language not in self.config["languages"]:
            return f"Error: language must be one of {list(self.config['languages'].keys())}"

        lang_config = self.config["languages"][language]
        lang_filter = lang_config["filter"]

        db_results = []
        query_variations = self._normalize_query(query)

        # Get dynamic type ordering
        type_order = self._get_type_order_clause()

        # Get top-level types from configuration
        if "types" in self.config and self.config["types"]:
            # Sort types by their priority value and take the first few
            sorted_types = sorted(self.config["types"].items(), key=lambda x: x[1])
            top_types = [type_name for type_name, _ in sorted_types[:5]]
        else:
            # If no types configured, we can't filter by type
            top_types = []

        type_list = ", ".join(f"'{t}'" for t in top_types) if top_types else "''"

        # Collect all results, not just from first successful query
        all_results: list[tuple[str, str, str]] = []
        seen_entries: set[tuple[str, str]] = (
            set()
        )  # Track (name, type) to avoid duplicates

        # Try exact match with all query variations (case-insensitive)
        for q in query_variations:
            cursor.execute(
                f"""
                SELECT name, type, path
                FROM searchIndex
                WHERE name = ? COLLATE NOCASE AND path LIKE ?
                ORDER BY {type_order}
                LIMIT ?
            """,
                (q, f"%{lang_filter}%", max_results),
            )
            for row in cursor.fetchall():
                key = (row[0], row[1])
                if key not in seen_entries:
                    all_results.append(row)
                    seen_entries.add(key)
            if len(all_results) >= max_results:
                break

        # If we need more results, try framework-level entries without language filter
        if len(all_results) < max_results:
            for q in query_variations:
                cursor.execute(
                    f"""
                    SELECT name, type, path
                    FROM searchIndex
                    WHERE name = ? COLLATE NOCASE
                    AND type IN ({type_list})
                    AND (path LIKE '%/documentation/%' OR path LIKE '%request_key=%')
                    ORDER BY {type_order}
                    LIMIT ?
                """,
                    (q, max_results - len(all_results)),
                )
                for row in cursor.fetchall():
                    key = (row[0], row[1])
                    if key not in seen_entries:
                        all_results.append(row)
                        seen_entries.add(key)
                if len(all_results) >= max_results:
                    break

        # Check if we found an exact match in the results
        found_exact_match: bool = False
        exact_match_name: str | None = None
        exact_match_path: str | None = None
        exact_match_type: str | None = None

        for row in all_results:
            if len(row) >= 3 and row[0].lower() == query.lower():
                found_exact_match = True
                exact_match_name = row[0]
                exact_match_type = row[1]
                exact_match_path = row[2]
                break

        # Track additional members count
        additional_members = 0

        # Count total members for exact matches to show in the note
        if found_exact_match and exact_match_name and exact_match_path:
            # Extract the documentation path pattern
            doc_path_pattern = ""
            if "/documentation/" in exact_match_path:
                doc_path = (
                    exact_match_path.split("/documentation/")[1]
                    .split("?")[0]
                    .split("#")[0]
                )
                doc_path_pattern = f"%/documentation/{doc_path}/%"

            if doc_path_pattern:
                # Count total members for the note (but don't include them in results)
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM searchIndex
                    WHERE path LIKE ?
                    AND path LIKE ?
                    AND name != ?
                """,
                    (doc_path_pattern, f"%{lang_filter}%", exact_match_name),
                )
                total_count = cursor.fetchone()
                if total_count:
                    additional_members = total_count[0]

        # If we still need more results, try broader search
        if len(all_results) < max_results:
            cursor.execute(
                f"""
                SELECT name, type, path,
                    CASE
                        WHEN name = ? COLLATE NOCASE THEN 0
                        WHEN type IN ({type_list}) AND name = ? COLLATE NOCASE THEN 1
                        WHEN name LIKE ? COLLATE NOCASE THEN 2
                        WHEN type IN ({type_list}) AND name LIKE ? COLLATE NOCASE THEN 3
                        ELSE 4
                    END as rank
                FROM searchIndex
                WHERE name LIKE ? COLLATE NOCASE
                AND (
                    (path LIKE ? AND path LIKE ?)  -- Has language filter
                    OR (type IN ({type_list}) AND (path LIKE '%/documentation/%' OR path LIKE '%request_key=%'))  -- Or is framework without language
                )
                ORDER BY rank, {type_order}, LENGTH(name)
                LIMIT ?
            """,
                (
                    query,
                    query,
                    f"{query}%",
                    f"{query}%",
                    f"%{query}%",
                    f"%{lang_filter}%",
                    f"%{lang_filter}%",
                    max_results * 2,
                ),
            )
            for row in cursor.fetchall():
                if len(all_results) >= max_results:
                    break
                key = (row[0], row[1])
                if key not in seen_entries:
                    all_results.append(row)
                    seen_entries.add(key)

        conn.close()

        # Use all_results instead of db_results
        db_results: list[tuple[str, str, str]] = all_results[:max_results]

        if not db_results:
            return f"No matches found for '{query}' in {language} documentation"

        # Extract documentation for each result
        results: list[str] = []
        for row in db_results[:max_results]:
            # Handle both 3-column and 4-column results (with or without rank)
            if len(row) == 4:
                name: str = str(row[0])
                doc_type: str = str(row[1])
                path: str = str(row[2])
                # Ignore rank column (row[3])
            else:
                name: str = str(row[0])
                doc_type: str = str(row[1])
                path: str = str(row[2])
            if self.config["format"] == "apple":
                if "request_key=" in path:
                    request_key: str = path.split("request_key=")[1].split("#")[0]
                    # Remove any language parameter from request_key
                    if "&" in request_key:
                        request_key = request_key.split("&")[0]

                    # If path contains language parameter, use that instead
                    path_language: str = language
                    if "&language=" in path:
                        path_language = (
                            path.split("&language=")[1].split("&")[0].split("#")[0]
                        )

                    doc = self._extract_by_request_key(request_key, path_language)

                    if doc:
                        markdown = self._format_as_markdown(doc, name, doc_type)

                        # Add member note if this is the exact match and has members
                        if (
                            found_exact_match
                            and name == exact_match_name
                            and doc_type == exact_match_type
                            and additional_members > 0
                        ):
                            type_note = f"\n\n**Note:** The {exact_match_name} {doc_type.lower()} contains {additional_members} additional members not shown. Use `search_docs('{exact_match_name}', language='{language}', max_results=50)` to see all {exact_match_name} members."
                            markdown += type_note

                        results.append(markdown)
            elif self.config["format"] == "tarix":
                # Extract HTML content from tarix archive
                html_content = self._extract_from_tarix(path)
                if html_content:
                    markdown = self._format_html_as_markdown(
                        html_content, name, doc_type, path
                    )

                    # Add member note if this is the exact match and has members
                    if (
                        found_exact_match
                        and name == exact_match_name
                        and doc_type == exact_match_type
                        and additional_members > 0
                    ):
                        type_note = f"\n\n**Note:** The {exact_match_name} {doc_type.lower()} contains {additional_members} additional members not shown. Use `search_docs('{exact_match_name}', language='{language}', max_results=50)` to see all {exact_match_name} members."
                        markdown += type_note

                    results.append(markdown)

        # Handle different result counts appropriately
        if results:
            if len(results) == 1:
                # Single result: return full content
                return results[0]
            elif 2 <= len(results) <= 5:
                # 2-5 results: return summaries with option to search individually
                summaries: list[str] = []
                for i, full_content in enumerate(results, 1):
                    lines = full_content.split("\n")
                    # Get title and key info
                    title = lines[0] if lines else f"Result {i}"
                    summary_lines = [f"{i}. {title}"]

                    # Add type and framework info
                    for line in lines[1:10]:
                        if line.startswith("**Type:**") or line.startswith(
                            "**Framework:**"
                        ):
                            summary_lines.append(f"   {line}")

                    # Add first line of summary if available
                    for j, line in enumerate(lines):
                        if line == "## Summary" and j + 2 < len(lines):
                            summary_text = lines[j + 2]
                            if len(summary_text) > 100:
                                summary_text = summary_text[:100] + "..."
                            summary_lines.append(f"   {summary_text}")
                            break

                    summaries.append("\n".join(summary_lines))

                header = f"Found {len(results)} results for '{query}':\n\n"
                footer = (
                    "\n\nSearch for each item individually to see full documentation."
                )
                return header + "\n\n".join(summaries) + footer
            elif len(results) <= 100:
                # 6-100 results: return full content with separators
                return "\n\n---\n\n".join(results)
            else:
                # More than 100: show count and suggest refinement
                # In future, could implement pagination here
                entry_list: list[str] = []
                for full_content in results[:100]:
                    lines = full_content.split("\n")
                    title = lines[0].replace("# ", "") if lines else "Unknown"
                    doc_type = "Unknown"
                    framework = ""
                    for line in lines[1:5]:
                        if line.startswith("**Type:**"):
                            doc_type = line.replace("**Type:** ", "")
                        elif line.startswith("**Framework:**"):
                            framework = f" - {line.replace('**Framework:** ', '')}"
                    entry_list.append(f"- {title} ({doc_type}{framework})")

                header = f"Found {len(results)} results for '{query}' (showing first 100):\n\n"
                footer = f"\n\nToo many results ({len(results)}). Consider refining your search or using list_entries() with filters."
                return header + "\n".join(entry_list) + footer

        # No results extracted
        if not db_results:
            return f"No matches found for '{query}' in {language} documentation"

        # Found entries but couldn't extract
        entries_info: list[str] = []
        for row in db_results[:10]:  # Show up to 10 entries found
            if len(row) == 4:
                name: str = str(row[0])
                doc_type: str = str(row[1])
                # path not needed for this output
            else:
                name: str = str(row[0])
                doc_type: str = str(row[1])
                # path not needed for this output
            entries_info.append(f"- {name} ({doc_type})")

        return f"""Found entries for '{query}' but couldn't extract documentation. The content may not be in the offline cache.

Found but couldn't extract:
{chr(10).join(entries_info)}

Try opening Dash and ensuring the '{self.config['name']}' docset is fully downloaded."""

    def list_frameworks(self, filter_text: str | None = None) -> str:
        """List available frameworks/modules"""
        conn = sqlite3.connect(self.optimized_db)
        cursor = conn.cursor()

        if self.config["format"] == "apple" and self.config.get("framework_pattern"):
            framework_pattern = self.config["framework_pattern"]

            if "documentation/" in framework_pattern:
                query = """
                    SELECT DISTINCT
                        SUBSTR(path,
                            INSTR(path, 'documentation/') + 14,
                            INSTR(SUBSTR(path, INSTR(path, 'documentation/') + 14), '/') - 1
                        ) as framework
                    FROM searchIndex
                    WHERE path LIKE '%documentation/%'
                """
            else:
                # Fallback to generic pattern matching
                query = f"""
                    SELECT DISTINCT path
                    FROM searchIndex
                    WHERE path LIKE '%{framework_pattern}%'
                    LIMIT 100
                """

            if filter_text:
                query = query.replace(
                    "WHERE", f"WHERE framework LIKE '%{filter_text}%' AND"
                )

            cursor.execute(query)

            if "documentation/" in framework_pattern:
                frameworks = [row[0] for row in cursor.fetchall() if row[0]]
            else:
                # Extract framework names from paths manually
                paths = [row[0] for row in cursor.fetchall()]
                frameworks: list[str] = []
                import re

                pattern_regex = framework_pattern.replace("([^/]+)", "([^/]+)")
                for path in paths:
                    match = re.search(pattern_regex, path)
                    if match and match.group(1):
                        frameworks.append(match.group(1))

            # Remove duplicates and empty strings
            frameworks = sorted(set(f for f in frameworks if f))

            label = "frameworks"
        else:
            # For other docsets, just list available types
            query = "SELECT DISTINCT type FROM searchIndex ORDER BY type"
            cursor.execute(query)
            frameworks = [row[0] for row in cursor.fetchall() if row[0]]
            label = "types"

        conn.close()

        if filter_text:
            return f"{label.title()} matching '{filter_text}':\n" + "\n".join(
                f"- {f}" for f in frameworks if filter_text.lower() in f.lower()
            )
        else:
            return f"Available {label} ({len(frameworks)} total):\n" + "\n".join(
                f"- {f}" for f in frameworks
            )

    def _extract_by_request_key(
        self, request_key: str, language: str = "swift"
    ) -> AppleDocumentation | None:
        """Extract documentation using request key and SHA-1 encoding"""
        # Convert request_key to canonical path
        if request_key.startswith("ls/"):
            canonical_path = "/" + request_key[3:]
        else:
            canonical_path = "/" + request_key

        # Calculate UUID using SHA-1
        sha1_hash = hashlib.sha1(canonical_path.encode("utf-8")).digest()
        truncated = sha1_hash[:6]
        suffix = base64.urlsafe_b64encode(truncated).decode().rstrip("=")

        # Language prefix from config
        lang_config = self.config["languages"][language]
        prefix = lang_config["prefix"]
        uuid = prefix + suffix

        conn = sqlite3.connect(self.cache_db)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT data_id, offset, length
            FROM refs
            WHERE uuid = ?
        """,
            (uuid,),
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            data_id, offset, length = result
            return self._extract_from_fs(data_id, offset, length)

        return None

    def _extract_from_fs(
        self, data_id: int, offset: int, length: int
    ) -> AppleDocumentation | None:
        """Extract JSON from fs file at specific offset"""
        fs_file = self.fs_dir / str(data_id)

        if not fs_file.exists():
            return None

        try:
            # Load and cache decompressed data
            if data_id not in self.fs_cache:
                with open(fs_file, "rb") as f:
                    compressed = f.read()
                self.fs_cache[data_id] = brotli.decompress(compressed)

            decompressed = self.fs_cache[data_id]

            # Extract JSON at offset
            json_data = decompressed[offset : offset + length]
            import json

            doc = json.loads(json_data)

            if "metadata" in doc:
                return doc

        except Exception:
            pass

        return None

    def _format_as_markdown(
        self, doc: AppleDocumentation, name: str, doc_type: str
    ) -> str:
        """Format documentation as Markdown"""
        lines: list[str] = []
        metadata = doc.get("metadata", {})

        # Title
        title = metadata.get("title", name)
        lines.append(f"# {title}")

        # Type
        lines.append(f"\n**Type:** {doc_type}")

        # Framework
        modules = metadata.get("modules", [])
        if modules:
            names = [m.get("name", "") for m in modules]
            lines.append(f"**Framework:** {', '.join(names)}")

        # Availability
        platforms = metadata.get("platforms", [])
        if platforms:
            avail: list[str] = []
            for p in platforms:
                platform_name = p.get("name", "")
                ver = p.get("introducedAt", "")
                if ver:
                    avail.append(f"{platform_name} {ver}+")
                else:
                    avail.append(platform_name)
            if avail:
                lines.append(f"**Available on:** {', '.join(avail)}")

        # Abstract/Summary
        abstract = doc.get("abstract", [])
        if abstract:
            text = self._extract_text(abstract)
            if text:
                lines.append(f"\n## Summary\n\n{text}")

        # Primary Content Sections
        sections = doc.get("primaryContentSections", [])
        for section in sections:
            kind = section.get("kind", "")

            if kind == "declarations":
                decls = section.get("declarations", [])
                if decls and decls[0].get("tokens"):
                    lines.append("\n## Declaration\n")
                    tokens = decls[0].get("tokens", [])
                    code = "".join(t.get("text", "") for t in tokens)
                    lang = decls[0].get("languages", ["swift"])[0]
                    lines.append(f"```{lang}\n{code}\n```")

            elif kind == "parameters":
                params = section.get("parameters", [])
                if params:
                    lines.append("\n## Parameters\n")
                    for param in params:
                        param_name = param.get("name", "")
                        param_content = param.get("content", [])
                        param_text = self._extract_text(param_content)
                        if param_name and param_text:
                            lines.append(f"- **{param_name}**: {param_text}")

            elif kind == "content":
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    lines.append(f"\n{text}")

            # Handle other section types as generic content
            elif "content" in section:
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    section_title = kind.replace("_", " ").title()
                    lines.append(f"\n## {section_title}\n\n{text}")

        # Discussion
        discussion = doc.get("discussionSections", [])
        if discussion:
            lines.append("\n## Discussion")
            for section in discussion:  # Get all discussion sections
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    lines.append(f"\n{text}")

        return "\n".join(lines)

    def _extract_text(self, content: list[ContentItem]) -> str:
        """Extract plain text from content"""
        parts: list[str] = []
        for item in content:
            t = item.get("type", "")
            if t == "text":
                parts.append(item.get("text", ""))
            elif t == "codeVoice":
                parts.append(f"`{item.get('code', '')}`")
            elif t == "paragraph":
                inline = item.get("inlineContent", [])
                parts.append(self._extract_text(inline))
            elif t == "reference":
                title = item.get("title", item.get("identifier", ""))
                parts.append(f"`{title}`")
        return " ".join(parts)

    def _extract_from_tarix(self, search_path: str) -> str | None:
        """Extract HTML content from tarix archive"""
        # Remove anchor from path
        clean_path = search_path.split("#")[0]

        # Handle special Dash metadata paths (like in C docset)
        if clean_path.startswith("<dash_entry_"):
            # Extract the actual file path from the end of the path
            # Format: <dash_entry_...>actual/file/path.html
            parts = clean_path.split(">")
            if len(parts) > 1:
                clean_path = parts[-1]  # Get the actual file path after the last >

        # Build full docset path
        # Extract docset folder name from docset_path (e.g., "NodeJS/NodeJS.docset" -> "NodeJS.docset")
        docset_folder = self.config["docset_path"].split("/")[-1]
        full_path = f"{docset_folder}/Contents/Resources/Documents/{clean_path}"

        # Check cache first
        if full_path in self.html_cache:
            return self.html_cache[full_path]

        try:
            # Query tarix index for file location
            conn = sqlite3.connect(self.tarix_index)
            cursor = conn.cursor()

            cursor.execute("SELECT hash FROM tarindex WHERE path = ?", (full_path,))
            result = cursor.fetchone()
            conn.close()

            if not result:
                return None

            # Validate hash format: "entry_number offset size"
            hash_parts = result[0].split()
            if len(hash_parts) != 3:
                return None

            # Extract file from tar archive
            with tarfile.open(self.tarix_archive, "r:gz") as tar:
                # Find the file by path name (entry_number doesn't seem to be sequential index)
                try:
                    target_member = tar.getmember(full_path)
                    extracted_file = tar.extractfile(target_member)
                    if extracted_file:
                        content = extracted_file.read().decode("utf-8", errors="ignore")
                        self.html_cache[full_path] = content
                        return content
                except KeyError:
                    # If exact path fails, try to find by name
                    target_file = full_path.split("/")[-1]  # Get just the filename
                    for member in tar.getmembers():
                        if (
                            member.name.endswith(target_file)
                            and clean_path in member.name
                        ):
                            extracted_file = tar.extractfile(member)
                            if extracted_file:
                                content = extracted_file.read().decode(
                                    "utf-8", errors="ignore"
                                )
                                self.html_cache[full_path] = content
                                return content

        except Exception:
            pass

        return None

    def _format_html_as_markdown(
        self, html_content: str, name: str, doc_type: str, path: str
    ) -> str:
        """Convert HTML documentation to Markdown"""
        lines: list[str] = []

        # Title
        lines.append(f"# {name}")

        # Type
        lines.append(f"\n**Type:** {doc_type}")

        # Path info
        lines.append(f"**Path:** {path}")

        # Try to extract key content from HTML
        # This is a simple text extraction - could be enhanced with proper HTML parsing
        import re

        # Remove HTML tags and extract text content
        text_content = re.sub(r"<[^>]+>", "", html_content)

        # Clean up whitespace
        text_content = re.sub(r"\s+", " ", text_content).strip()

        # Limit content length
        if len(text_content) > 2000:
            text_content = text_content[:2000] + "..."

        if text_content:
            lines.append(f"\n## Content\n\n{text_content}")

        return "\n".join(lines)


class CheatsheetExtractor:
    """Extract content from Dash cheatsheets"""

    def __init__(self, name: str, cheatsheets_base_path: str | None = None):
        self.name = name

        # Build list of paths to search for cheatsheets
        search_paths: list[Path] = []

        # Use custom cheatsheet location if provided, otherwise use configured paths
        if cheatsheets_base_path:
            search_paths.append(Path(os.path.expanduser(cheatsheets_base_path)))
        else:
            # Check environment variable for custom location
            env_path = os.getenv("CHEATSHEET_PATH")
            if env_path:
                search_paths.append(Path(os.path.expanduser(env_path)))

            # Add additional paths from global config
            if docsetmcp_config.additional_cheatsheet_paths:
                additional_paths = docsetmcp_config.parse_path_list(
                    docsetmcp_config.additional_cheatsheet_paths
                )
                search_paths.extend([Path(p) for p in additional_paths])

            # If no custom paths specified, use default Dash location
            if not search_paths:
                search_paths.append(
                    Path(
                        os.path.expanduser(
                            "~/Library/Application Support/Dash/Cheat Sheets"
                        )
                    )
                )

        # Find the cheatsheet in the search paths
        self.cheatsheet_dir: Path | None = None
        for search_path in search_paths:
            self.cheatsheets_path = search_path  # Set for _find_cheatsheet_dir
            found_dir = self._find_cheatsheet_dir(name)
            if found_dir:
                self.cheatsheet_dir = found_dir
                break

        # If not found, default to first search path for error reporting
        if self.cheatsheet_dir is None:
            self.cheatsheets_path = search_paths[0]
            raise FileNotFoundError(f"Cheatsheet '{name}' not found")

        # Find the .docset within the directory
        docset_files = list(self.cheatsheet_dir.glob("*.docset"))
        if not docset_files:
            raise FileNotFoundError(f"No .docset found in {self.cheatsheet_dir}")

        self.docset = docset_files[0]
        self.db_path = self.docset / "Contents/Resources/docSet.dsidx"
        self.documents_path = self.docset / "Contents/Resources/Documents"

    def _find_cheatsheet_dir(self, name: str) -> Path | None:
        """Find cheatsheet directory using smart heuristics"""
        # Direct match
        direct_path = self.cheatsheets_path / name
        if direct_path.exists():
            return direct_path

        # Case-insensitive match
        for path in self.cheatsheets_path.iterdir():
            if path.is_dir() and path.name.lower() == name.lower():
                return path

        # Fuzzy match - contains the name
        for path in self.cheatsheets_path.iterdir():
            if path.is_dir() and name.lower() in path.name.lower():
                return path

        # Replace common separators and try again
        variations = [
            name.replace("-", " "),
            name.replace("_", " "),
            name.replace("-", ""),
            name.replace("_", ""),
            name.title(),
            name.upper(),
        ]

        for variant in variations:
            for path in self.cheatsheets_path.iterdir():
                if path.is_dir() and (
                    path.name.lower() == variant.lower()
                    or variant.lower() in path.name.lower()
                ):
                    return path

        return None

    def get_categories(self) -> list[str]:
        """Get all categories from the cheatsheet database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT DISTINCT name
            FROM searchIndex
            WHERE type = 'Category'
            ORDER BY name
        """
        )

        categories = [row[0] for row in cursor.fetchall()]
        conn.close()

        return categories

    def get_category_content(self, category_name: str) -> str:
        """Get all entries from a specific category"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all entries for this category
        # The category is referenced in the path for entries
        # Need to handle URL encoding in the path
        import urllib.parse

        encoded_category = urllib.parse.quote(category_name)

        cursor.execute(
            """
            SELECT name, type, path
            FROM searchIndex
            WHERE (path LIKE ? OR path LIKE ?) AND type = 'Entry'
            ORDER BY name
        """,
            (f"%dash_ref_{category_name}/%", f"%dash_ref_{encoded_category}/%"),
        )

        entries = cursor.fetchall()
        conn.close()

        if not entries:
            return f"No entries found in category '{category_name}'"

        # Now extract the content from HTML for each entry
        html_path = self.documents_path / "index.html"

        if not html_path.exists():
            return f"No content file found for {self.name} cheatsheet"

        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Build the result
            result: list[str] = [f"# {self.name} - {category_name}\n"]

            # Debug: show how many entries we're processing
            # result.append(f"_Processing {len(entries)} entries..._\n")

            for entry_name, _, entry_path in entries:
                # Find the specific entry in the HTML
                # Look for the table row with this entry's ID from the path
                entry_id = entry_path.split("#")[-1] if "#" in entry_path else None

                if entry_id:
                    # URL decode the entry_id since HTML uses spaces, not %20
                    import urllib.parse

                    entry_id = urllib.parse.unquote(entry_id)

                    # Also create version with & replaced by &amp; for HTML
                    entry_id_html = entry_id.replace("&", "&amp;")
                    # Find the table row with this ID
                    import re

                    # Pattern to find the specific entry
                    # Try multiple patterns since HTML might vary
                    patterns = [
                        rf"<tr[^>]*id='{re.escape(entry_id)}'[^>]*>(.*?)</tr>",
                        rf'<tr[^>]*id="{re.escape(entry_id)}"[^>]*>(.*?)</tr>',
                        rf"<tr[^>]*id=['\"]?{re.escape(entry_id)}['\"]?[^>]*>(.*?)</tr>",
                        # Also try with HTML-encoded ampersand
                        rf"<tr[^>]*id='{re.escape(entry_id_html)}'[^>]*>(.*?)</tr>",
                        rf'<tr[^>]*id="{re.escape(entry_id_html)}"[^>]*>(.*?)</tr>',
                    ]

                    tr_match = None
                    for pattern in patterns:
                        tr_match = re.search(
                            pattern, html_content, re.DOTALL | re.IGNORECASE
                        )
                        if tr_match:
                            break

                    if tr_match:
                        tr_html = tr_match.group(1)

                        # Extract the content from this row
                        result.append(f"\n## {entry_name}")

                        # Extract notes/content
                        notes_pattern = r'<div class=[\'"]notes[\'"]>(.*?)</div>'
                        notes_matches = re.findall(
                            notes_pattern, tr_html, re.DOTALL | re.IGNORECASE
                        )

                        # Also check for command column (like in Xcode cheatsheet)
                        command_pattern = (
                            r'<td class=[\'"]command[\'"]>.*?<code>(.*?)</code>'
                        )
                        command_match = re.search(
                            command_pattern, tr_html, re.DOTALL | re.IGNORECASE
                        )

                        if command_match:
                            # This is a command-style entry (like Xcode)
                            command = command_match.group(1).strip()
                            # Clean up HTML entities
                            command = (
                                command.replace("&lt;", "<")
                                .replace("&gt;", ">")
                                .replace("&amp;", "&")
                                .replace("&#39;", "'")
                                .replace("&quot;", '"')
                            )
                            result.append(f"```\n{command}\n```")

                        # Check if we have any non-empty notes
                        # has_content = False
                        # for notes in notes_matches:
                        #     if notes.strip():
                        #         has_content = True
                        #         break

                        for notes in notes_matches:
                            if not notes.strip():
                                continue

                            # Extract code blocks
                            code_pattern = r"<pre[^>]*>(.*?)</pre>"
                            code_matches = re.findall(
                                code_pattern, notes, re.DOTALL | re.IGNORECASE
                            )

                            # Replace code blocks with placeholders
                            temp_notes = notes
                            for idx, code in enumerate(code_matches):
                                temp_notes = re.sub(
                                    rf"<pre[^>]*>{re.escape(code)}</pre>",
                                    f"__CODE_{idx}__",
                                    temp_notes,
                                )

                            # Extract inline code
                            inline_code_pattern = r"<code[^>]*>(.*?)</code>"
                            inline_codes = re.findall(
                                inline_code_pattern, temp_notes, re.IGNORECASE
                            )

                            # Replace inline code with placeholders
                            for idx, code in enumerate(inline_codes):
                                temp_notes = re.sub(
                                    f"<code[^>]*>{re.escape(code)}</code>",
                                    f"__INLINE_{idx}__",
                                    temp_notes,
                                )

                            # Remove all HTML tags
                            text = re.sub(r"<[^>]+>", " ", temp_notes)

                            # Restore code blocks
                            for idx, code in enumerate(code_matches):
                                # Clean up HTML entities in code
                                code = (
                                    code.replace("&lt;", "<")
                                    .replace("&gt;", ">")
                                    .replace("&amp;", "&")
                                )
                                text = text.replace(
                                    f"__CODE_{idx}__", f"\n```\n{code}\n```\n"
                                )

                            # Restore inline code
                            for idx, code in enumerate(inline_codes):
                                code = (
                                    code.replace("&lt;", "<")
                                    .replace("&gt;", ">")
                                    .replace("&amp;", "&")
                                )
                                text = text.replace(f"__INLINE_{idx}__", f"`{code}`")

                            # Clean up whitespace
                            text = re.sub(r"\s+", " ", text).strip()
                            text = re.sub(
                                r"\s*\n\s*```", "\n```", text
                            )  # Clean code block formatting
                            text = re.sub(r"```\s*\n\s*", "```\n", text)

                            # Clean up remaining HTML entities
                            text = (
                                text.replace("&lt;", "<")
                                .replace("&gt;", ">")
                                .replace("&amp;", "&")
                                .replace("&#39;", "'")
                                .replace("&quot;", '"')
                            )

                            if text:
                                result.append(text)

            return "\n".join(result)

        except Exception as e:
            return f"Error extracting category content: {str(e)}"

    def search(self, query: str = "", category: str = "", max_results: int = 10) -> str:
        """Search cheatsheet entries"""
        # If no query and no category, return the full content
        if not query and not category:
            return self.get_full_content()

        # If only category is specified, return that category's content
        if category and not query:
            return self.get_category_content(category)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build search query
        if query and category:
            # Search within a specific category
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE (name LIKE ? OR name = ?)
                AND path LIKE ?
                ORDER BY
                    CASE
                        WHEN name = ? THEN 0
                        WHEN name LIKE ? THEN 1
                        ELSE 2
                    END,
                    CASE type
                        WHEN 'Category' THEN 0
                        ELSE 1
                    END
                LIMIT ?
            """,
                (f"%{query}%", query, f"%{category}%", query, f"{query}%", max_results),
            )
        elif query:
            # General search
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE name LIKE ? OR name = ?
                ORDER BY
                    CASE
                        WHEN name = ? THEN 0
                        WHEN name LIKE ? THEN 1
                        ELSE 2
                    END,
                    CASE type
                        WHEN 'Category' THEN 0
                        ELSE 1
                    END
                LIMIT ?
            """,
                (f"%{query}%", query, query, f"{query}%", max_results),
            )
        else:
            # List all categories
            cursor.execute(
                """
                SELECT name, type, path
                FROM searchIndex
                WHERE type = 'Category'
                ORDER BY name
                LIMIT ?
            """,
                (max_results,),
            )

        results = cursor.fetchall()
        conn.close()

        if not results:
            return f"No results found in {self.name} cheatsheet"

        # Format results
        lines: list[str] = [f"# {self.name} Cheatsheet\n"]

        for name, entry_type, path in results:
            if entry_type == "Category":
                lines.append(f"\n## {name}")
            else:
                # Extract the actual content from HTML
                content = self._extract_entry_content(path, name)
                if content:
                    lines.append(f"\n### {name}")
                    lines.append(content)

        return "\n".join(lines)

    def _extract_entry_content(self, _path: str, name: str) -> str | None:
        """Extract entry content from HTML"""
        # For cheatsheets, the path is usually index.html with anchors
        html_path = self.documents_path / "index.html"

        if not html_path.exists():
            return None

        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Simple extraction - find the entry and its associated code
            # This is a simplified approach; real implementation would use proper HTML parsing
            import re

            # Look for the entry in the HTML
            pattern = rf'<td class="description">{re.escape(name)}</td>\s*<td class="command">(.*?)</td>'
            match = re.search(pattern, html_content, re.DOTALL | re.IGNORECASE)

            if match:
                command = match.group(1)
                # Clean up HTML tags
                command = re.sub(r"<[^>]+>", "", command)
                command = command.strip()
                return f"```\n{command}\n```"

            return None

        except Exception:
            return None

    def get_full_content(self) -> str:
        """Extract the full content of the cheatsheet"""
        html_path = self.documents_path / "index.html"

        if not html_path.exists():
            return f"No content found for {self.name} cheatsheet"

        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # Convert HTML to markdown-style text
            import re

            # Remove script and style elements
            html_content = re.sub(
                r"<(script|style)[^>]*>.*?</\1>",
                "",
                html_content,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Extract title
            title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE)
            title = title_match.group(1) if title_match else self.name

            # Extract main description (from article > p)
            desc_match = re.search(
                r"<article>\s*<p>(.*?)</p>", html_content, re.DOTALL | re.IGNORECASE
            )
            description = ""
            if desc_match:
                description = desc_match.group(1)
                # Clean nested tags
                description = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", description)
                description = re.sub(r"<[^>]+>", "", description)
                description = re.sub(r"\s+", " ", description).strip()

            # Process sections
            sections: list[str] = []

            # Find all section.category blocks
            section_pattern = r'<section class=[\'"]category[\'"]>(.*?)</section>'
            section_matches = re.findall(
                section_pattern, html_content, re.DOTALL | re.IGNORECASE
            )

            for section_html in section_matches:
                # Extract section title from h2
                h2_match = re.search(
                    r"<h2[^>]*>\s*(.*?)\s*</h2>", section_html, re.IGNORECASE
                )
                if not h2_match:
                    continue

                section_title = h2_match.group(1).strip()

                # Extract all entries in this section
                entries: list[str] = []

                # Find all table rows with entries
                tr_pattern = r"<tr[^>]*>(.*?)</tr>"
                tr_matches = re.findall(
                    tr_pattern, section_html, re.DOTALL | re.IGNORECASE
                )

                for tr_html in tr_matches:
                    # Extract entry name
                    name_match = re.search(
                        r'<div class=[\'"]name[\'"]>\s*<p>(.*?)</p>',
                        tr_html,
                        re.DOTALL | re.IGNORECASE,
                    )
                    if not name_match:
                        continue

                    entry_name = name_match.group(1).strip()

                    # Extract notes/content
                    notes_pattern = r'<div class=[\'"]notes[\'"]>(.*?)</div>'
                    notes_matches = re.findall(
                        notes_pattern, tr_html, re.DOTALL | re.IGNORECASE
                    )

                    entry_content: list[str] = []
                    for notes in notes_matches:
                        if not notes.strip():
                            continue

                        # Extract code blocks
                        code_pattern = r"<pre[^>]*>(.*?)</pre>"
                        code_matches = re.findall(
                            code_pattern, notes, re.DOTALL | re.IGNORECASE
                        )

                        # Replace code blocks with placeholders
                        temp_notes = notes
                        for idx, code in enumerate(code_matches):
                            temp_notes = temp_notes.replace(
                                f'<pre class="highlight plaintext">{code}</pre>',
                                f"__CODE_{idx}__",
                            )
                            temp_notes = temp_notes.replace(
                                f"<pre>{code}</pre>", f"__CODE_{idx}__"
                            )

                        # Extract inline code
                        inline_code_pattern = r"<code[^>]*>(.*?)</code>"
                        inline_codes = re.findall(
                            inline_code_pattern, temp_notes, re.IGNORECASE
                        )

                        # Replace inline code with placeholders
                        for idx, code in enumerate(inline_codes):
                            temp_notes = re.sub(
                                f"<code[^>]*>{re.escape(code)}</code>",
                                f"__INLINE_{idx}__",
                                temp_notes,
                            )

                        # Remove all HTML tags
                        text = re.sub(r"<[^>]+>", " ", temp_notes)

                        # Restore code blocks
                        for idx, code in enumerate(code_matches):
                            # Clean up HTML entities in code
                            code = (
                                code.replace("&lt;", "<")
                                .replace("&gt;", ">")
                                .replace("&amp;", "&")
                                .replace("&#39;", "'")
                                .replace("&quot;", '"')
                            )
                            text = text.replace(
                                f"__CODE_{idx}__", f"\\n```\\n{code}\\n```\\n"
                            )

                        # Restore inline code
                        for idx, code in enumerate(inline_codes):
                            code = (
                                code.replace("&lt;", "<")
                                .replace("&gt;", ">")
                                .replace("&amp;", "&")
                            )
                            text = text.replace(f"__INLINE_{idx}__", f"`{code}`")

                        # Clean up whitespace
                        text = re.sub(r"\\s+", " ", text).strip()
                        text = re.sub(
                            r"\\s*\\n\\s*```", "\\n```", text
                        )  # Clean code block formatting
                        text = re.sub(r"```\\s*\\n\\s*", "```\\n", text)

                        if text:
                            entry_content.append(text)

                    if entry_content:
                        entries.append(
                            f"### {entry_name}\n" + "\n\n".join(entry_content)
                        )

                if entries:
                    sections.append(f"## {section_title}\n" + "\n\n".join(entries))

            # Extract footer/notes section
            notes_section_match = re.search(
                r'<section class=[\'"]notes[\'"]>(.*?)</section>',
                html_content,
                re.DOTALL | re.IGNORECASE,
            )
            if notes_section_match:
                notes_html = notes_section_match.group(1)
                # Extract h2
                h2_match = re.search(r"<h2[^>]*>(.*?)</h2>", notes_html, re.IGNORECASE)
                if h2_match:
                    notes_title = h2_match.group(1).strip()
                    # Extract content
                    notes_content = re.sub(r"<h2[^>]*>.*?</h2>", "", notes_html)
                    notes_content = re.sub(r"<a[^>]*>(.*?)</a>", r"\\1", notes_content)
                    notes_content = re.sub(r"<[^>]+>", " ", notes_content)
                    notes_content = re.sub(r"\\s+", " ", notes_content).strip()

                    if notes_content:
                        sections.append(f"## {notes_title}\\n{notes_content}")

            # Build the final output
            result: list[str] = [f"# {title}"]

            if description:
                result.append(f"\n{description}")

            if sections:
                result.append("\n" + "\n\n".join(sections))

            return "\n".join(result)

        except Exception as e:
            return f"Error extracting content from {self.name} cheatsheet: {str(e)}"


# Global configuration class to hold runtime settings
class DocsetMCPConfig:
    def __init__(self):
        self.docset_path: str | None = None
        self.cheatsheet_path: str | None = None
        self.additional_docset_paths: list[str] = []
        self.additional_cheatsheet_paths: list[str] = []

    def parse_path_list(self, value: str | list[str] | None) -> list[str]:
        """Parse path list from various input formats"""
        if not value:
            return []
        if isinstance(value, list):
            return [os.path.expanduser(p) for p in value if p.strip()]
        # Must be str at this point since we've ruled out None and list
        return [os.path.expanduser(p.strip()) for p in value.split(":") if p.strip()]


# Global config instance
docsetmcp_config = DocsetMCPConfig()

# Initialize extractors for available docsets (will be populated by initialize_extractors)
extractors: dict[str, DashExtractor] = {}

# Initialize cheatsheet extractors (will be populated as needed)
cheatsheet_extractors: dict[str, CheatsheetExtractor] = {}


def initialize_extractors():
    """Initialize extractors with current configuration"""
    global extractors
    extractors.clear()

    # Load available docset configs using new system
    try:
        from .config_loader import ConfigLoader
    except ImportError:
        from docsetmcp.config_loader import ConfigLoader

    loader = ConfigLoader()
    try:
        # Pass additional docset paths for auto-detection
        additional_paths = []
        if docsetmcp_config.additional_docset_paths:
            additional_paths = docsetmcp_config.parse_path_list(docsetmcp_config.additional_docset_paths)
        
        all_configs = loader.load_all_configs(additional_paths if additional_paths else None)

        # Try to initialize each docset
        for docset_type, config in all_configs.items():
            try:
                # Create a modified DashExtractor that uses the provided config
                extractor = DashExtractor.__new__(DashExtractor)
                extractor.config = config
                
                # Build list of paths to search for docsets
                search_paths: list[str] = []
                
                # Use custom docset location if provided, otherwise use configured paths
                if docsetmcp_config.docset_path:
                    search_paths.append(os.path.expanduser(docsetmcp_config.docset_path))
                else:
                    # Check environment variable for custom location
                    env_path = os.getenv("DOCSET_PATH")
                    if env_path:
                        search_paths.append(os.path.expanduser(env_path))

                    # Add additional paths from global config
                    if docsetmcp_config.additional_docset_paths:
                        additional_search_paths = docsetmcp_config.parse_path_list(
                            docsetmcp_config.additional_docset_paths
                        )
                        search_paths.extend(additional_search_paths)

                    # If no custom paths specified, use default Dash location
                    if not search_paths:
                        search_paths.append(
                            os.path.expanduser("~/Library/Application Support/Dash/DocSets")
                        )

                # Find the docset in the search paths
                extractor.docset = None
                for search_path in search_paths:
                    potential_docset = Path(search_path) / config["docset_path"]
                    if potential_docset.exists():
                        extractor.docset = potential_docset
                        break

                # If not found, skip this docset
                if extractor.docset is None:
                    continue
                    
                # Set up paths based on docset format
                if config["format"] == "apple":
                    extractor.fs_dir = extractor.docset / "Contents/Resources/Documents/fs"
                    extractor.optimized_db = extractor.docset / "Contents/Resources/optimizedIndex.dsidx"
                    extractor.cache_db = extractor.docset / "Contents/Resources/Documents/cache.db"
                    # Cache for decompressed fs files
                    extractor.fs_cache = {}
                elif config["format"] == "tarix":
                    extractor.optimized_db = extractor.docset / "Contents/Resources/optimizedIndex.dsidx"
                    extractor.tarix_archive = extractor.docset / "Contents/Resources/tarix.tgz"
                    extractor.tarix_index = extractor.docset / "Contents/Resources/tarixIndex.db"
                    # Cache for extracted HTML content
                    extractor.html_cache = {}

                # Check if docset exists
                if not extractor.docset.exists():
                    continue

                extractors[docset_type] = extractor
                
            except Exception as e:
                # Debug: print what went wrong
                print(f"Warning: Failed to initialize {docset_type}: {e}")
                pass

    except Exception:
        # If config system fails, extractors will be empty
        # This is handled gracefully by the tool functions
        pass


# Initialize extractors with default configuration on module load
initialize_extractors()


@mcp.tool()
def search_docs(
    query: str,
    docset: str,
    language: str | None = None,
    max_results: int = 3,
) -> str:
    """
    Search and extract documentation from Dash docsets by EXACT NAME MATCHING.

    IMPORTANT: This tool searches for EXACT NAMES of documentation entries, NOT keyword search.
    Only use this when you know the specific name of a class, function, framework, or API.
    For discovery, use list_types and list_entries tools first.

    Search behavior:
    - Exact matches first (e.g., 'CarPlay' → CarPlay framework)
    - Prefix matches second (e.g., 'CarPlay' → 'carPlaySetting')
    - Substring matches last (e.g., 'CarPlay' → 'allowInCarPlay')

    Args:
        query: EXACT NAME of the documentation entry to find
               Examples: 'CarPlay', 'UIViewController', 'readFile', 'ModelContext'
               NOT keywords like 'file handling' or 'image processing'
        docset: Docset to search in (e.g., 'apple_api_reference', 'nodejs', 'bash')
        language: Programming language variant (optional, varies by docset)
                  For Apple docs: 'swift' or 'objc'
        max_results: Maximum number of results to return (1-10, default: 3)

    For discovery/exploration:
    - Use list_types(docset, language) to see available types (Class, Protocol, etc.)
    - Use list_entries(docset, type_name, language, name_filter) to browse entries by type
    - Use list_frameworks(docset, filter) to find frameworks containing keywords

    Returns:
        Formatted Markdown documentation with exact matches prioritized.
        Container types (frameworks, classes) include drilldown notes for exploring members.
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    extractor = extractors[docset]

    if not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"

    # Use docset-specific default language if none provided
    if language is None:
        # Get the first configured language as default
        config = extractor.config
        if "languages" in config and config["languages"]:
            language = next(iter(config["languages"]))
        else:
            language = "swift"  # Fallback for compatibility

    return extractor.search(query, language, max_results)


@mcp.tool()
def list_available_docsets() -> str:
    """
    List all available docsets with detailed information for easy querying.

    This tool provides a comprehensive list of all installed docsets including:
    - Docset identifier (use this for the 'docset' parameter)
    - Full name and description
    - Supported languages
    - Example query command

    Returns:
        Formatted list of available docsets with usage examples
    """
    if not extractors:
        return (
            "No docsets are currently available. Please check your Dash installation."
        )

    lines = ["# Available Dash Docsets\n"]
    lines.append("Use these docset identifiers with the `search_docs` tool:\n")

    for docset_id, extractor in sorted(extractors.items()):
        config = extractor.config
        languages = list(config.get("languages", {}).keys())
        lang_str = (
            ", ".join(f"`{lang}`" for lang in languages)
            if languages
            else "no languages"
        )

        lines.append(f"## {config.get('name', docset_id)}")

        if "description" in config:
            lines.append(f"*{config['description']}*\n")

        lines.append(f"- **Docset ID:** `{docset_id}`")
        lines.append(f"- **Languages:** {lang_str}")

        # Add example query
        default_lang = languages[0] if languages else None
        if default_lang:
            lines.append(
                f'- **Example:** `search_docs("YourQuery", docset="{docset_id}", language="{default_lang}")`'
            )
        else:
            lines.append(
                f'- **Example:** `search_docs("YourQuery", docset="{docset_id}")`'
            )

        lines.append("")  # Empty line between docsets

    return "\n".join(lines)


@mcp.tool()
def list_frameworks(docset: str, filter: str | None = None) -> str:
    """
    List available frameworks/types in a specific docset.

    Args:
        docset: Docset to list from (e.g., 'nodejs', 'python_3', 'bash')
        filter: Optional filter for framework/type names

    Returns:
        List of available frameworks or types
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    return extractors[docset].list_frameworks(filter)


@mcp.tool()
def list_languages() -> str:
    """
    List all programming languages with available documentation and descriptions.

    This tool provides a comprehensive overview of all supported languages,
    their associated docsets, and descriptions to help you find the right documentation.

    Returns:
        Detailed list of languages with docsets, descriptions, and usage examples
    """
    if not extractors:
        return (
            "No docsets are currently available. Please check your Dash installation."
        )

    # Group docsets by language
    language_map: dict[str, list[DocsetInfo]] = {}

    for docset_type, extractor in extractors.items():
        config = extractor.config

        # Get the primary language(s) for this docset
        primary_lang = config.get("primary_language")
        if primary_lang is not None:
            lang = primary_lang
            if lang not in language_map:
                language_map[lang] = []
            language_map[lang].append(
                {
                    "docset": docset_type,
                    "name": config["name"],
                    "languages": list(config["languages"].keys()),
                    "description": config.get("description"),
                }
            )
        else:
            # Infer from docset name or type
            name = config["name"].lower()
            if "javascript" in name or "js" in name:
                lang = "JavaScript"
            elif "typescript" in name:
                lang = "TypeScript"
            elif "python" in name:
                lang = "Python"
            elif "ruby" in name:
                lang = "Ruby"
            elif "java" in name and "javascript" not in name:
                lang = "Java"
            elif "bash" in name or "shell" in name:
                lang = "Shell"
            elif "sql" in name:
                lang = "SQL"
            elif name in ["c", "c++"]:
                lang = name.upper()
            elif "swift" in name or "apple" in name:
                lang = "Swift"
            elif "html" in name:
                lang = "HTML"
            elif "css" in name:
                lang = "CSS"
            elif "docker" in name:
                lang = "Docker"
            elif "react" in name:
                lang = "React"
            elif "vue" in name:
                lang = "Vue"
            else:
                # Use the docset name as language
                lang = config["name"]

            if lang not in language_map:
                language_map[lang] = []
            language_map[lang].append(
                {
                    "docset": docset_type,
                    "name": config["name"],
                    "languages": (
                        list(config["languages"].keys())
                        if "languages" in config
                        else []
                    ),
                    "description": config.get("description"),
                }
            )

    # Format output
    lines = ["# Available Languages and Their Documentation\n"]
    lines.append(
        "Explore documentation by language, then drill down into specific docsets and types.\n"
    )

    for lang in sorted(language_map.keys()):
        docsets = language_map[lang]
        lines.append(f"## {lang}")
        lines.append(f"*{len(docsets)} docset(s) available*\n")

        for ds in docsets:
            lines.append(f"### {ds['name']}")

            # Add description if available
            if ds.get("description"):
                lines.append(f"*{ds['description']}*\n")

            lines.append(f"- **Docset ID:** `{ds['docset']}`")

            # Show language variants if available
            if ds["languages"]:
                lang_str = ", ".join(f"`{l}`" for l in ds["languages"])
                lines.append(f"- **Language variants:** {lang_str}")

            # Add example commands
            lines.append("\n**Quick start commands:**")
            lines.append(f"```")
            lines.append(f"# List all types in this docset")
            lines.append(f"list_types(\"{ds['docset']}\")")
            if ds["languages"]:
                lines.append(f"\n# List types for specific language")
                lines.append(
                    f"list_types(\"{ds['docset']}\", language=\"{ds['languages'][0]}\")"
                )
            lines.append(f"\n# Search for specific documentation")
            lines.append(f"search_docs(\"YourQuery\", docset=\"{ds['docset']}\")")
            lines.append(f"```")
            lines.append("")

        lines.append("---\n")

    lines.append(
        f"**Summary:** {len(language_map)} languages, {len(extractors)} docsets total"
    )
    lines.append("\n**Next steps:**")
    lines.append('1. Use `list_types("docset_id")` to explore documentation types')
    lines.append(
        '2. Use `list_entries("docset_id", type="TypeName")` to browse entries'
    )
    lines.append("3. Use `search_docs()` to find specific documentation")

    return "\n".join(lines)


@mcp.tool()
def list_docsets_by_language(language: str) -> str:
    """
    Find all docsets that provide documentation for a specific programming language.

    This tool helps you find relevant documentation for a specific language,
    returning ready-to-use examples for querying.

    Args:
        language: The programming language to search for (e.g., 'python', 'javascript', 'swift')

    Returns:
        Formatted list of docsets with usage examples for the specified language
    """
    if not extractors:
        return (
            "No docsets are currently available. Please check your Dash installation."
        )

    language_lower = language.lower()
    matching_docsets: list[tuple[str, MatchedDocsetInfo]] = []

    for docset_type, extractor in extractors.items():
        config = extractor.config
        name_lower = config["name"].lower()

        # Check various ways a docset might be related to the language
        matches = False
        matched_lang = None

        # Direct name match
        if language_lower in name_lower:
            matches = True
            # Get the first available language variant
            if "languages" in config:
                matched_lang = next(iter(config["languages"].keys()))

        # Check language variants
        elif "languages" in config:
            for lang_key in config["languages"].keys():
                if language_lower in lang_key.lower():
                    matches = True
                    matched_lang = lang_key
                    break

        # Special cases
        elif language_lower in ["js", "javascript"] and (
            "javascript" in name_lower or "js" in name_lower or "node" in name_lower
        ):
            matches = True
        elif language_lower in ["ts", "typescript"] and "typescript" in name_lower:
            matches = True
        elif language_lower == "shell" and (
            "bash" in name_lower or "shell" in name_lower
        ):
            matches = True
        elif language_lower == "objective-c" and "apple" in name_lower:
            matches = True
        elif language_lower in ["swift", "swiftui"] and "apple" in name_lower:
            matches = True

        if matches:
            matched_info: MatchedDocsetInfo = {
                "config": config,
                "matched_lang": matched_lang,
            }
            matching_docsets.append((docset_type, matched_info))

    if not matching_docsets:
        return f"No docsets found for language '{language}'. Try 'list_languages' to see available options."

    # Format output
    lines = [f"# Docsets for {language.title()}\n"]
    lines.append("Use these with the `search_docs` tool:\n")

    for docset_id, info in matching_docsets:
        config = info["config"]
        matched_lang = info["matched_lang"]

        lines.append(f"## {config['name']}")

        if config.get("description"):
            lines.append(f"*{config['description']}*\n")

        lines.append(f"- **Docset ID:** `{docset_id}`")

        if "languages" in config:
            lang_str = ", ".join(f"`{lang}`" for lang in config["languages"].keys())
            lines.append(f"- **Languages:** {lang_str}")

        # Show the example with the matched language if available
        if matched_lang:
            lines.append(
                f'- **Example:** `search_docs("YourQuery", docset="{docset_id}", language="{matched_lang}")`'
            )
        elif "languages" in config and config["languages"]:
            default_lang = next(iter(config["languages"].keys()))
            lines.append(
                f'- **Example:** `search_docs("YourQuery", docset="{docset_id}", language="{default_lang}")`'
            )
        else:
            lines.append(
                f'- **Example:** `search_docs("YourQuery", docset="{docset_id}")`'
            )

        lines.append("")

    lines.append(f"Found {len(matching_docsets)} docset(s) for {language}")

    return "\n".join(lines)


@mcp.tool()
def list_types(docset: str, language: str | None = None) -> str:
    """
    List all documentation types available in a docset with examples.

    This shows the hierarchy of documentation types (e.g., Class, Method, Function)
    available in a docset, with example entries for each type.

    Args:
        docset: Docset identifier (e.g., 'apple_api_reference', 'nodejs')
        language: Optional language filter (e.g., 'swift', 'objc')

    Returns:
        List of types with example entries and counts
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    extractor = extractors[docset]
    config = extractor.config

    # Get the database connection
    conn = sqlite3.connect(extractor.optimized_db)
    cursor = conn.cursor()

    # Build language filter if specified
    lang_filter = ""
    if language:
        if language not in config.get("languages", {}):
            return f"Error: language '{language}' not available for {config['name']}. Available: {list(config.get('languages', {}).keys())}"
        lang_filter = config["languages"][language]["filter"]

    # Get type counts and examples
    lines = [f"# Documentation Types in {config['name']}"]
    if language:
        lines.append(f"*Filtered by language: {language}*\n")
    else:
        lines.append("")

    # Query for types with counts
    if lang_filter:
        cursor.execute(
            """
            SELECT type, COUNT(*) as count
            FROM searchIndex
            WHERE path LIKE ?
            GROUP BY type
            ORDER BY count DESC
        """,
            (f"%{lang_filter}%",),
        )
    else:
        cursor.execute(
            """
            SELECT type, COUNT(*) as count
            FROM searchIndex
            GROUP BY type
            ORDER BY count DESC
        """
        )

    type_counts = cursor.fetchall()

    if not type_counts:
        conn.close()
        return f"No types found in {config['name']}" + (
            f" for language {language}" if language else ""
        )

    for doc_type, count in type_counts:
        lines.append(f"## {doc_type} ({count:,} entries)")

        # Get 3 examples for this type
        if lang_filter:
            cursor.execute(
                """
                SELECT name
                FROM searchIndex
                WHERE type = ? AND path LIKE ?
                ORDER BY LENGTH(name), name
                LIMIT 3
            """,
                (doc_type, f"%{lang_filter}%"),
            )
        else:
            cursor.execute(
                """
                SELECT name
                FROM searchIndex
                WHERE type = ?
                ORDER BY LENGTH(name), name
                LIMIT 3
            """,
                (doc_type,),
            )

        examples = cursor.fetchall()
        if examples:
            lines.append("Examples:")
            for (name,) in examples:
                lines.append(f"- `{name}`")
        lines.append("")

    # Add usage hint
    lines.append("---")
    usage_hint = f'Use `list_entries(docset="{docset}", type="TypeName"'
    if language:
        usage_hint += f', language="{language}"'
    usage_hint += ")` to see all entries of a specific type."
    lines.append(usage_hint)

    conn.close()
    return "\n".join(lines)


@mcp.tool()
def list_entries(
    docset: str,
    type: str | None = None,
    language: str | None = None,
    starts_with: str | None = None,
    contains: str | None = None,
    max_results: int = 50,
) -> str:
    """
    List documentation entries with flexible filtering options.

    This tool allows you to browse documentation entries with various filters
    to find exactly what you're looking for.

    Args:
        docset: Docset identifier (e.g., 'apple_api_reference', 'nodejs')
        type: Filter by documentation type (e.g., 'Class', 'Method', 'Function')
        language: Filter by language (e.g., 'swift', 'objc')
        starts_with: Filter entries starting with this prefix (e.g., 'UI', 'NS')
        contains: Filter entries containing this substring
        max_results: Maximum results to return (1-200, default 50)

    Returns:
        List of matching documentation entries
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    if not 1 <= max_results <= 200:
        return "Error: max_results must be between 1 and 200"

    extractor = extractors[docset]
    config = extractor.config

    # Build query conditions
    conditions: list[str] = []
    params: list[Union[str, int]] = []

    if type:
        conditions.append("type = ?")
        params.append(type)

    if language and language in config.get("languages", {}):
        lang_filter = config["languages"][language]["filter"]
        conditions.append("path LIKE ?")
        params.append(f"%{lang_filter}%")

    if starts_with:
        conditions.append("name LIKE ?")
        params.append(f"{starts_with}%")

    if contains:
        conditions.append("name LIKE ?")
        params.append(f"%{contains}%")

    # Build the query
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    conn = sqlite3.connect(extractor.optimized_db)
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT name, type
        FROM searchIndex
        WHERE {where_clause}
        ORDER BY name
        LIMIT ?
    """,
        params + [max_results],
    )

    results = cursor.fetchall()
    conn.close()

    if not results:
        filters: list[str] = []
        if type:
            filters.append(f"type={type}")
        if language:
            filters.append(f"language={language}")
        if starts_with:
            filters.append(f"starts_with={starts_with}")
        if contains:
            filters.append(f"contains={contains}")
        return (
            f"No entries found in {config['name']} with filters: {', '.join(filters)}"
        )

    # Format output
    lines = [f"# Documentation Entries in {config['name']}"]

    # Show active filters
    if type or language or starts_with or contains:
        lines.append("\nActive filters:")
        if type:
            lines.append(f"- Type: {type}")
        if language:
            lines.append(f"- Language: {language}")
        if starts_with:
            lines.append(f"- Starts with: {starts_with}")
        if contains:
            lines.append(f"- Contains: {contains}")
        lines.append("")

    # Group by type if not filtering by type
    if not type:
        from collections import defaultdict

        by_type: defaultdict[str, list[str]] = defaultdict(list)
        for name, doc_type in results:
            by_type[doc_type].append(name)

        for doc_type, names in sorted(by_type.items()):
            lines.append(f"## {doc_type} ({len(names)})")
            for name in names[:10]:  # Show first 10 of each type
                lines.append(f"- `{name}`")
            if len(names) > 10:
                lines.append(f"- ... and {len(names) - 10} more")
            lines.append("")
    else:
        # Just list all entries
        lines.append(f"## {type} entries ({len(results)})\n")
        for name, _ in results:
            lines.append(f"- `{name}`")

    lines.append("\n---")
    lines.append(f"Showing {len(results)} of {max_results} max results.")
    search_hint = f'Use `search_docs("{results[0][0]}", docset="{docset}"'
    if language:
        search_hint += f', language="{language}"'
    search_hint += ")` to see full documentation."
    lines.append(search_hint)

    return "\n".join(lines)


@mcp.tool()
def search_cheatsheet(
    cheatsheet: str, query: str = "", category: str = "", max_results: int = 10
) -> str:
    """
    Search a Dash cheatsheet for quick reference information.

    Args:
        cheatsheet: Name of the cheatsheet (e.g., 'git', 'vim', 'docker')
        query: Optional search query within the cheatsheet
        category: Optional category to filter results
        max_results: Maximum number of results (1-50)

    Returns:
        Formatted cheatsheet entries
    """
    if not 1 <= max_results <= 50:
        return "Error: max_results must be between 1 and 50"

    # Try to get or create the cheatsheet extractor
    if cheatsheet not in cheatsheet_extractors:
        try:
            cheatsheet_extractors[cheatsheet] = CheatsheetExtractor(
                cheatsheet, docsetmcp_config.cheatsheet_path
            )
        except FileNotFoundError:
            available = list_available_cheatsheets()
            return f"Error: Cheatsheet '{cheatsheet}' not found.\n\n{available}"

    return cheatsheet_extractors[cheatsheet].search(query, category, max_results)


@mcp.tool()
def list_available_cheatsheets() -> str:
    """
    List all available Dash cheatsheets.

    Returns:
        List of available cheatsheets
    """
    # Use configured cheatsheet path or default
    if docsetmcp_config.cheatsheet_path:
        cheatsheets_path = Path(os.path.expanduser(docsetmcp_config.cheatsheet_path))
    else:
        # Check environment variable
        env_path = os.getenv("CHEATSHEET_PATH")
        if env_path:
            cheatsheets_path = Path(os.path.expanduser(env_path))
        else:
            cheatsheets_path = Path(
                os.path.expanduser("~/Library/Application Support/Dash/Cheat Sheets")
            )

    if not cheatsheets_path.exists():
        return f"Cheatsheets directory not found at {cheatsheets_path}."

    cheatsheets: list[str] = []
    for path in sorted(cheatsheets_path.iterdir()):
        if path.is_dir() and list(path.glob("*.docset")):
            # Extract simple name from directory
            name = path.name
            # Try to make it more command-friendly
            simple_name = name.lower().replace(" ", "-")
            cheatsheets.append(f"- **{simple_name}**: {name}")

    if not cheatsheets:
        return "No cheatsheets found. Please download some from Dash."

    lines = ["Available cheatsheets:"] + cheatsheets
    lines.append(
        "\nUse the simplified name (e.g., 'git' instead of 'Git') when searching."
    )

    return "\n".join(lines)


@mcp.tool()
def list_cheatsheet_categories(cheatsheet: str) -> str:
    """
    List all categories in a specific cheatsheet.

    Args:
        cheatsheet: Name of the cheatsheet (e.g., 'git', 'macports', 'docker')

    Returns:
        List of categories in the cheatsheet
    """
    # Try to get or create the cheatsheet extractor
    if cheatsheet not in cheatsheet_extractors:
        try:
            cheatsheet_extractors[cheatsheet] = CheatsheetExtractor(
                cheatsheet, docsetmcp_config.cheatsheet_path
            )
        except FileNotFoundError:
            return f"Error: Cheatsheet '{cheatsheet}' not found."

    extractor = cheatsheet_extractors[cheatsheet]
    categories = extractor.get_categories()

    if not categories:
        return f"No categories found in {cheatsheet} cheatsheet."

    lines = [f"# {cheatsheet.title()} Cheatsheet Categories\n"]
    for cat in categories:
        lines.append(f"- {cat}")

    lines.append(
        f"\n\nUse these category names with search_cheatsheet to filter results."
    )

    return "\n".join(lines)


@mcp.tool()
def fetch_cheatsheet(cheatsheet: str) -> str:
    """
    Fetch the entire content of a Dash cheatsheet.

    This is the recommended way to access cheatsheet data when you need
    comprehensive information or want to browse all available commands.

    Args:
        cheatsheet: Name of the cheatsheet (e.g., 'git', 'vim', 'docker')

    Returns:
        Complete cheatsheet content formatted as Markdown
    """
    # Try to get or create the cheatsheet extractor
    if cheatsheet not in cheatsheet_extractors:
        try:
            cheatsheet_extractors[cheatsheet] = CheatsheetExtractor(
                cheatsheet, docsetmcp_config.cheatsheet_path
            )
        except FileNotFoundError:
            available = list_available_cheatsheets()
            return f"Error: Cheatsheet '{cheatsheet}' not found.\n\n{available}"

    return cheatsheet_extractors[cheatsheet].get_full_content()


def main():
    """Main entry point for the MCP server"""
    import sys
    import argparse

    try:
        from . import __version__
    except ImportError:
        from docsetmcp import __version__

    parser = argparse.ArgumentParser(
        prog="docsetmcp",
        description="Model Context Protocol server for Dash-style docsets",
        epilog="For more information, visit: https://github.com/codybrom/docsetmcp",
    )

    parser.add_argument(
        "--version", "-v", action="version", version=f"DocsetMCP {__version__}"
    )

    parser.add_argument(
        "--list-docsets",
        action="store_true",
        help="List all available docsets and exit",
    )

    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Test MCP server startup and exit",
    )

    parser.add_argument(
        "--docset-path",
        type=str,
        help="Custom path to docsets directory (overrides DOCSET_PATH environment variable)",
    )

    parser.add_argument(
        "--cheatsheet-path",
        type=str,
        help="Custom path to cheatsheets directory (overrides CHEATSHEET_PATH environment variable)",
    )

    parser.add_argument(
        "--additional-docset-paths",
        nargs="*",
        help="Additional docset paths to search in addition to default location",
    )

    parser.add_argument(
        "--additional-cheatsheet-paths",
        nargs="*",
        help="Additional cheatsheet paths to search in addition to default location",
    )

    # Parse args but allow for no args (normal MCP mode)
    args = parser.parse_args()

    # Update global configuration with CLI arguments
    if args.docset_path:
        docsetmcp_config.docset_path = args.docset_path
        # Re-initialize extractors with new path
        initialize_extractors()

    if args.cheatsheet_path:
        docsetmcp_config.cheatsheet_path = args.cheatsheet_path

    if args.additional_docset_paths:
        docsetmcp_config.additional_docset_paths = args.additional_docset_paths
        # Re-initialize extractors with new paths
        initialize_extractors()

    if args.additional_cheatsheet_paths:
        docsetmcp_config.additional_cheatsheet_paths = args.additional_cheatsheet_paths

    # Handle special commands
    if args.list_docsets:
        print("Available DocsetMCP docsets:")
        if extractors:
            for docset_id, extractor in sorted(extractors.items()):
                config = extractor.config
                languages = list(config.get("languages", {}).keys())
                lang_str = ", ".join(languages) if languages else "no languages"
                print(f"  {docset_id}: {config.get('name', docset_id)} ({lang_str})")
            print(f"\nTotal: {len(extractors)} docsets available")
        else:
            print("  No docsets found. Please install docsets in Dash.app first.")
        return

    if args.test_connection:
        print(f"DocsetMCP {__version__}")
        print("Testing MCP server startup...")
        try:
            # Quick initialization test
            print(f"✓ Found {len(extractors)} docset(s)")
            print(f"✓ Found {len(cheatsheet_extractors)} cheatsheet(s) cached")
            print("✓ MCP server initialized successfully")
            print("\nStarting MCP server (use Ctrl+C to stop)...")
            # Fall through to normal MCP mode for a few seconds to test
        except Exception as e:
            print(f"✗ Error initializing MCP server: {e}")
            sys.exit(1)

    # Normal MCP server mode
    mcp.run()


if __name__ == "__main__":
    main()
