#!/usr/bin/env python3
"""
Dash MCP Server - Extract documentation from Dash docsets as Markdown
"""

import os
import sqlite3
import brotli
import hashlib
import base64
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List

# MCP SDK imports
from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("Dash")


class DashExtractor:
    def __init__(self, docset_type: str = "apple"):
        # Load docset configuration using new config loader
        from .config_loader import ConfigLoader

        loader = ConfigLoader()

        # Map legacy names
        if docset_type == "apple":
            docset_type = "apple_api_reference"

        try:
            self.config = loader.load_config(docset_type)
        except FileNotFoundError:
            raise ValueError(f"Unsupported docset type: {docset_type}")

        # Default Dash docset location on macOS
        dash_docsets_path = os.path.expanduser(
            "~/Library/Application Support/Dash/DocSets"
        )
        self.docset = (
            Path(dash_docsets_path)
            / self.config["docset_name"]
            / self.config["docset_path"]
        )
        # Set up paths based on docset format
        if self.config["format"] == "apple":
            self.fs_dir = self.docset / "Contents/Resources/Documents/fs"
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.cache_db = self.docset / "Contents/Resources/Documents/cache.db"
            # Cache for decompressed fs files
            self._fs_cache = {}
        elif self.config["format"] == "tarix":
            self.optimized_db = self.docset / "Contents/Resources/optimizedIndex.dsidx"
            self.tarix_archive = self.docset / "Contents/Resources/tarix.tgz"
            self.tarix_index = self.docset / "Contents/Resources/tarixIndex.db"
            # Cache for extracted HTML content
            self._html_cache = {}

        # Check if Dash docset exists
        if not self.docset.exists():
            raise FileNotFoundError(
                f"{self.config['name']} not found in Dash. "
                "Please download it in Dash.app first"
            )

    def search(self, query: str, language: str = "swift", max_results: int = 3) -> str:
        """Search for Apple API documentation"""
        results = []

        # Search the optimized index
        conn = sqlite3.connect(self.optimized_db)
        cursor = conn.cursor()

        # Filter by language using config
        if language not in self.config["languages"]:
            return f"Error: language must be one of {list(self.config['languages'].keys())}"

        lang_config = self.config["languages"][language]
        lang_filter = lang_config["filter"]

        # Exact match first
        cursor.execute(
            """
            SELECT name, type, path 
            FROM searchIndex 
            WHERE name = ? AND path LIKE ?
            ORDER BY 
                CASE type 
                    WHEN 'Protocol' THEN 0
                    WHEN 'Class' THEN 1
                    WHEN 'Struct' THEN 2
                    ELSE 3 
                END
            LIMIT ?
        """,
            (query, f"%{lang_filter}%", max_results),
        )

        db_results = cursor.fetchall()

        if not db_results:
            # Try partial match
            cursor.execute(
                """
                SELECT name, type, path 
                FROM searchIndex 
                WHERE name LIKE ? AND path LIKE ?
                ORDER BY LENGTH(name)
                LIMIT ?
            """,
                (f"%{query}%", f"%{lang_filter}%", max_results),
            )
            db_results = cursor.fetchall()

        conn.close()

        if not db_results:
            return f"No matches found for '{query}' in {language} documentation"

        # Extract documentation for each result
        for name, doc_type, path in db_results[:max_results]:
            if self.config["format"] == "apple":
                if "request_key=" in path:
                    request_key = path.split("request_key=")[1].split("#")[0]
                    doc = self._extract_by_request_key(request_key, language)

                    if doc:
                        markdown = self._format_as_markdown(doc, name, doc_type)
                        results.append(markdown)
            elif self.config["format"] == "tarix":
                # Extract HTML content from tarix archive
                html_content = self._extract_from_tarix(path)
                if html_content:
                    markdown = self._format_html_as_markdown(
                        html_content, name, doc_type, path
                    )
                    results.append(markdown)

        if not results:
            return f"Found entries for '{query}' but couldn't extract documentation. The content may not be in the offline cache."

        return "\n\n---\n\n".join(results)

    def list_frameworks(self, filter_text: Optional[str] = None) -> str:
        """List available frameworks/modules"""
        conn = sqlite3.connect(self.optimized_db)
        cursor = conn.cursor()

        if self.config["format"] == "apple" and self.config["framework_path_extract"]:
            # Use framework path pattern from config for Apple docs
            framework_pattern = self.config["framework_path_pattern"]
            extract_config = self.config["framework_path_extract"]
            start_offset = extract_config["start_offset"]

            query = f"""
                SELECT DISTINCT 
                    SUBSTR(path, 
                        INSTR(path, '{extract_config["start_marker"]}') + {start_offset},
                        INSTR(SUBSTR(path, INSTR(path, '{extract_config["start_marker"]}') + {start_offset}), '{extract_config["end_marker"]}') - 1
                    ) as framework
                FROM searchIndex
                WHERE path LIKE '%{framework_pattern}%'
            """

            if filter_text:
                query += f" AND framework LIKE '%{filter_text}%'"

            query += " ORDER BY framework"

            cursor.execute(query)
            frameworks = [row[0] for row in cursor.fetchall() if row[0]]

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
    ) -> Optional[Dict[str, Any]]:
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
    ) -> Optional[Dict[str, Any]]:
        """Extract JSON from fs file at specific offset"""
        fs_file = self.fs_dir / str(data_id)

        if not fs_file.exists():
            return None

        try:
            # Load and cache decompressed data
            if data_id not in self._fs_cache:
                with open(fs_file, "rb") as f:
                    compressed = f.read()
                self._fs_cache[data_id] = brotli.decompress(compressed)

            decompressed = self._fs_cache[data_id]

            # Extract JSON at offset
            json_data = decompressed[offset : offset + length]
            import json

            doc = json.loads(json_data)

            if "metadata" in doc:
                return doc

        except Exception:
            pass

        return None

    def _format_as_markdown(self, doc: Dict[str, Any], name: str, doc_type: str) -> str:
        """Format documentation as Markdown"""
        lines = []
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
            avail = []
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

        # Declaration
        sections = doc.get("primaryContentSections", [])
        for section in sections:
            if section.get("kind") == "declarations":
                decls = section.get("declarations", [])
                if decls and decls[0].get("tokens"):
                    lines.append("\n## Declaration\n")
                    tokens = decls[0].get("tokens", [])
                    code = "".join(t.get("text", "") for t in tokens)
                    lang = decls[0].get("languages", ["swift"])[0]
                    lines.append(f"```{lang}\n{code}\n```")
                break

        # Discussion
        discussion = doc.get("discussionSections", [])
        if discussion:
            lines.append("\n## Discussion")
            for section in discussion[:2]:  # Limit to first 2 sections
                content = section.get("content", [])
                text = self._extract_text(content)
                if text:
                    lines.append(f"\n{text}")

        return "\n".join(lines)

    def _extract_text(self, content: List[Dict[str, Any]]) -> str:
        """Extract plain text from content"""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
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
        return ""

    def _extract_from_tarix(self, search_path: str) -> Optional[str]:
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
        full_path = f"{self.config['docset_name']}.docset/Contents/Resources/Documents/{clean_path}"

        # Check cache first
        if full_path in self._html_cache:
            return self._html_cache[full_path]

        try:
            # Query tarix index for file location
            conn = sqlite3.connect(self.tarix_index)
            cursor = conn.cursor()

            cursor.execute("SELECT hash FROM tarindex WHERE path = ?", (full_path,))
            result = cursor.fetchone()
            conn.close()

            if not result:
                return None

            # Parse hash: "entry_number offset size"
            hash_parts = result[0].split()
            if len(hash_parts) != 3:
                return None

            _, offset, size = map(
                int, hash_parts
            )  # entry_number not used as sequential index

            # Extract file from tar archive
            with tarfile.open(self.tarix_archive, "r:gz") as tar:
                # Find the file by path name (entry_number doesn't seem to be sequential index)
                try:
                    target_member = tar.getmember(full_path)
                    extracted_file = tar.extractfile(target_member)
                    if extracted_file:
                        content = extracted_file.read().decode("utf-8", errors="ignore")
                        self._html_cache[full_path] = content
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
                                self._html_cache[full_path] = content
                                return content

        except Exception:
            pass

        return None

    def _format_html_as_markdown(
        self, html_content: str, name: str, doc_type: str, path: str
    ) -> str:
        """Convert HTML documentation to Markdown"""
        lines = []

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

    def __init__(self, name: str):
        self.name = name
        self.cheatsheets_path = Path(
            os.path.expanduser("~/Library/Application Support/Dash/Cheat Sheets")
        )

        # Find the cheatsheet using heuristics
        self.cheatsheet_dir = self._find_cheatsheet_dir(name)
        if not self.cheatsheet_dir:
            raise FileNotFoundError(f"Cheatsheet '{name}' not found")

        # Find the .docset within the directory
        docset_files = list(self.cheatsheet_dir.glob("*.docset"))
        if not docset_files:
            raise FileNotFoundError(f"No .docset found in {self.cheatsheet_dir}")

        self.docset = docset_files[0]
        self.db_path = self.docset / "Contents/Resources/docSet.dsidx"
        self.documents_path = self.docset / "Contents/Resources/Documents"

    def _find_cheatsheet_dir(self, name: str) -> Optional[Path]:
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

    def get_categories(self) -> List[str]:
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
            result = [f"# {self.name} - {category_name}\n"]

            # Debug: show how many entries we're processing
            # result.append(f"_Processing {len(entries)} entries..._\n")

            for entry_name, entry_type, entry_path in entries:
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
                        has_content = False
                        for notes in notes_matches:
                            if notes.strip():
                                has_content = True
                                break

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
        lines = [f"# {self.name} Cheatsheet\n"]

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

    def _extract_entry_content(self, path: str, name: str) -> Optional[str]:
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
            sections = []

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
                entries = []

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

                    entry_content = []
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
                            f"### {entry_name}\\n{'\\n\\n'.join(entry_content)}"
                        )

                if entries:
                    sections.append(f"## {section_title}\\n" + "\\n\\n".join(entries))

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
            result = [f"# {title}"]

            if description:
                result.append(f"\\n{description}")

            if sections:
                result.append("\\n" + "\\n\\n".join(sections))

            return "\\n".join(result)

        except Exception as e:
            return f"Error extracting content from {self.name} cheatsheet: {str(e)}"


# Initialize extractors for available docsets
extractors = {}

# Initialize cheatsheet extractors
cheatsheet_extractors = {}

# Load available docset configs using new system
from .config_loader import ConfigLoader

loader = ConfigLoader()
try:
    all_configs = loader.load_all_configs()

    # Try to initialize each docset
    for docset_type, config in all_configs.items():
        try:
            extractors[docset_type] = DashExtractor(docset_type)
            print(f"Loaded docset: {config['name']}")
        except FileNotFoundError:
            print(f"Docset not found: {config['name']}")

    # Add legacy "apple" alias for backward compatibility
    if "apple_api_reference" in extractors:
        extractors["apple"] = extractors["apple_api_reference"]

except Exception as e:
    print(f"Warning: Could not load new config system, falling back to legacy: {e}")

    # Fallback to legacy system
    config_path = Path(__file__).parent / "docsets.json"
    with open(config_path) as f:
        legacy_configs = json.load(f)

    for docset_type in legacy_configs.keys():
        try:
            extractors[docset_type] = DashExtractor(docset_type)
            print(f"Loaded docset: {legacy_configs[docset_type]['name']}")
        except FileNotFoundError:
            print(f"Docset not found: {legacy_configs[docset_type]['name']}")


@mcp.tool()
def search_docs(
    query: str, docset: str = "apple", language: str = "swift", max_results: int = 3
) -> str:
    """
    Search and extract documentation from Dash docsets as Markdown.

    Args:
        query: The API/function name to search for (e.g., 'AppIntent', 'fs.readFile', 'echo')
        docset: Docset to search in ('apple', 'nodejs', 'bash', etc.)
        language: Programming language variant (varies by docset)
        max_results: Maximum number of results to return (1-10)

    Returns:
        Formatted Markdown documentation
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    extractor = extractors[docset]

    if not 1 <= max_results <= 10:
        return "Error: max_results must be between 1 and 10"

    return extractor.search(query, language, max_results)


@mcp.tool()
def list_available_docsets() -> str:
    """
    List all available Dash docsets that can be searched.

    Returns:
        List of available docsets with their names
    """
    if not extractors:
        return (
            "No docsets are currently available. Please check your Dash installation."
        )

    lines = ["Available docsets:"]
    for docset_type, extractor in extractors.items():
        config = extractor.config
        languages = list(config["languages"].keys())
        lines.append(
            f"- **{docset_type}**: {config['name']} (languages: {', '.join(languages)})"
        )

    return "\n".join(lines)


@mcp.tool()
def list_frameworks(docset: str = "apple", filter: str | None = None) -> str:
    """
    List available frameworks/types in a specific docset.

    Args:
        docset: Docset to list from ('apple', 'nodejs', 'bash', etc.)
        filter: Optional filter for framework/type names

    Returns:
        List of available frameworks or types
    """
    if docset not in extractors:
        available = list(extractors.keys())
        return f"Error: docset '{docset}' not available. Available: {available}"

    return extractors[docset].list_frameworks(filter)


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
            cheatsheet_extractors[cheatsheet] = CheatsheetExtractor(cheatsheet)
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
    cheatsheets_path = Path(
        os.path.expanduser("~/Library/Application Support/Dash/Cheat Sheets")
    )

    if not cheatsheets_path.exists():
        return "No Dash cheatsheets directory found."

    cheatsheets = []
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
            cheatsheet_extractors[cheatsheet] = CheatsheetExtractor(cheatsheet)
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


def main():
    """Main entry point for the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
