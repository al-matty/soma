"""Soma configuration - paths, database location, API keys."""

import os
from pathlib import Path

# Project root
ROOT_DIR = Path(__file__).parent

# Load .env file if present
_env_file = ROOT_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Data paths
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "soma.duckdb"

# Profile paths
PROFILE_DIR = ROOT_DIR / "profile"
TEMPLATE_DIR = PROFILE_DIR / "templates"

# Documentation paths
DOCS_DIR = ROOT_DIR / "docs"
FINDINGS_DIR = DOCS_DIR / "findings"
PROFILE_DOCS_DIR = DOCS_DIR / "profile"

# dbt paths
DBT_DIR = ROOT_DIR / "dbt_project"

# Prompts
PROMPTS_DIR = ROOT_DIR / "prompts"

# API configuration
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
EXTRACTION_MODEL = "claude-opus-4-6"    # "claude-sonnet-4-20250514"
