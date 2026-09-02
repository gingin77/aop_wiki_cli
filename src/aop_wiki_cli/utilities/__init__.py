"""
Utilities Module
================

Shared helper functions and general-purpose utilities.

This module provides:
- File I/O operations (JSON, YAML, TSV)
- Logging setup
- Data caching utilities
- HTTP download utilities
- AOP-Wiki URL generation
- HTML to CSV conversion

Public API
----------

File I/O:
    to_json_serializable: Recursively convert Python objects to JSON-safe values
    to_json_string: Convert a value to a JSON string (for CSV/Excel cells)
    write_dict_to_json: Write dictionary to JSON file
    get_dict_from_json: Load dictionary from JSON file
    get_dict_from_tsv: Load dictionary from TSV file
    load_yaml_file: Load and parse YAML file

Caching:
    generic_cache_wrapper: Generic caching wrapper for data collection

Logging:
    set_up_logger: Configure and return a logger instance

Downloads:
    download_with_retry: Download file with retry logic using curl

AOP-Wiki URLs:
    get_single_aopwiki_url: Generate URL for a single AOP-Wiki entity
    get_aopwiki_urls: Generate URLs for multiple entities

HTML Conversion:
    convert_html_to_csv: Convert HTML table to CSV
"""

# File I/O
from aop_wiki_cli.utilities.helpers import (
    to_json_serializable,
    to_json_string,
    write_dict_to_json,
    get_dict_from_json,
    get_dict_from_tsv,
    load_yaml_file,
    get_dated_cache_dir
)

# Operations
from aop_wiki_cli.utilities.helpers import (
    generic_cache_wrapper,
    set_up_logger,
    download_with_retry,
    format_elapsed
)

# AOP-Wiki URLs
from aop_wiki_cli.utilities.helpers import (
    get_single_aopwiki_url,
    get_aopwiki_urls,
)

# HTML conversion
from aop_wiki_cli.utilities.html_to_csv_converter import convert_html_to_csv

__all__ = [
    # File I/O
    'to_json_serializable',
    'to_json_string',
    'write_dict_to_json',
    'get_dict_from_json',
    'get_dict_from_tsv',
    'load_yaml_file',
    'get_dated_cache_dir',
    # Caching
    'generic_cache_wrapper',
    # Logging
    'set_up_logger',
    # Downloads
    'download_with_retry',
    # URLs
    'get_single_aopwiki_url',
    'get_aopwiki_urls',
    # HTML
    'convert_html_to_csv',
    # Benchmarking
    'format_elapsed'
]
