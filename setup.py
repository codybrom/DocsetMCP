#!/usr/bin/env python3

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [
        line.strip() for line in fh if line.strip() and not line.startswith("#")
    ]

setup(
    name="dashmcp",
    version="0.1.1",
    author="Cody Bromley",
    author_email="dev@codybrom.com",
    description="Search local documentation from Dash through MCP",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/codybrom/dashmcp",
    packages=find_packages(),
    package_data={
        "dashmcp": ["config/docsets/*.yaml", "config/cheatsheets/*.yaml"],
    },
    include_package_data=True,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Documentation",
        "Topic :: Utilities",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "dashmcp=dashmcp.server:main",
        ],
    },
    keywords="mcp model-context-protocol dash documentation llm",
    project_urls={
        "Bug Reports": "https://github.com/codybrom/dashmcp/issues",
        "Source": "https://github.com/codybrom/dashmcp",
    },
)
