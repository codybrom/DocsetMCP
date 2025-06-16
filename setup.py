#!/usr/bin/env python3

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [
        line.strip() for line in fh if line.strip() and not line.startswith("#")
    ]

setup(
    name="docsetmcp",
    version="0.3.2",
    author="Cody Bromley",
    author_email="dev@codybrom.com",
    description="Search local documentation from Dash through MCP",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/codybrom/docsetmcp",
    packages=find_packages(),
    package_data={
        "docsetmcp": ["docsets/*.yaml", "py.typed"],
    },
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: MacOS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Documentation",
        "Topic :: Utilities",
        "Typing :: Typed",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "docsetmcp=docsetmcp.server:main",
        ],
    },
    keywords="mcp model-context-protocol dash documentation llm docset",
    project_urls={
        "Bug Reports": "https://github.com/codybrom/docsetmcp/issues",
        "Source": "https://github.com/codybrom/docsetmcp",
    },
)
