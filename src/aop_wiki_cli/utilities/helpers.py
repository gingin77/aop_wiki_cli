import os
import json
import time
import logging
import subprocess
import yaml
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any

from aop_wiki_cli.paths import ensure_dir, logs_dir

# ============================================================================
# UTILITY FUNCTIONS - File I/O and data loading
# ============================================================================

def get_dated_cache_dir(cache_root_path, work_date: date) -> Path:
    """Return the centralized cache directory path for the given work date."""
    return Path(cache_root_path) / work_date.strftime("%m-%d-%Y")

def get_dict_from_tsv(filepath, logger):
    """Load JSON dictionary from file path."""
    if os.path.exists(filepath):
        data_dict = json.load(open(filepath, 'r', encoding='utf-8'))
        logger.info(f"Loaded data dictionary from {filepath}")
    else:
        logger.error(f"Data file not found at {filepath}. Cannot proceed.")
        return
    return data_dict


def to_json_serializable(value, _seen=None):
    """
    Recursively convert common Python values into JSON-serializable values.

    Supports nested dict/list structures and converts set-like/tuple values
    into lists. Datetime/date values are converted to ISO 8601 strings.
    """
    if _seen is None:
        _seen = set()

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            (key if isinstance(key, (str, int, float, bool)) or key is None else str(key)):
            to_json_serializable(item, _seen)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [to_json_serializable(item, _seen) for item in value]

    if isinstance(value, (set, frozenset, tuple)):
        serialized_items = [to_json_serializable(item, _seen) for item in value]
        return sorted(serialized_items, key=str) if isinstance(value, (set, frozenset)) else serialized_items

    if hasattr(value, '__dict__'):
        object_id = id(value)
        if object_id in _seen:
            return str(value)

        _seen.add(object_id)
        return {
            str(key): to_json_serializable(item, _seen)
            for key, item in vars(value).items()
        }

    return str(value)


def to_json_string(value):
    """
    Convert a value to a JSON string.
    
    Unlike to_json_serializable (which returns Python objects), this returns
    a string suitable for embedding in CSV/Excel cells.
    
    Args:
        value: Any value that can be JSON serialized (list, dict, etc.)
        
    Returns:
        JSON string representation or empty string if None/empty
    """
    if value is None or value == [] or value == {}:
        return ''
    try:
        return json.dumps(to_json_serializable(value), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def write_dict_to_json(data, output_dir, filename):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    serializable_data = to_json_serializable(data)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serializable_data, f, indent=2, ensure_ascii=False)
    item_count = len(serializable_data) if hasattr(serializable_data, '__len__') else 1
    print(f"✓ JSON written to {output_path} ({item_count} items)")

def generic_cache_wrapper(cache_key, cache_dir, data_collector, force_refresh=False, logger=None):
    """
    Generic caching wrapper that can be reused for any data collection operation.
    
    This function provides core caching logic that can be applied to any data
    collection scenario - not just XML entity collection.
    
    Args:
        cache_key: Unique identifier for this cache (used in filename without extension)
        cache_dir: Directory to store cached files
        data_collector: Callable that returns the data to cache (takes no args)
        force_refresh: If True, ignore cache and collect fresh data
        logger: Optional logger instance for status messages
    
    Returns:
        Cached or freshly collected data (dict)
    """
    cache_file = f'{cache_key}.json'
    cache_path = os.path.join(cache_dir, cache_file)
    
    # Try to load from cache
    if not force_refresh and os.path.exists(cache_path):
        if logger:
            logger.info(f"Loading cached data from {cache_file}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if logger:
            logger.info(f"✓ Loaded {len(data)} items from cache")
        return data
    
    # Collect fresh data
    if logger:
        if force_refresh:
            logger.info("Force refresh enabled - collecting fresh data...")
        else:
            logger.info("Cache not found - collecting fresh data...")
    
    data = data_collector()
    
    # Cache the result
    os.makedirs(cache_dir, exist_ok=True)
    write_dict_to_json(data, cache_dir, cache_file)
    
    return data

def get_dict_from_json(filepath):
    """Load JSON dictionary from file path."""
    if os.path.exists(filepath):
        return json.load(open(filepath, 'r', encoding='utf-8'))

def load_yaml_file(filepath: str) -> Dict[str, Any]:
    """Load and parse a YAML file."""
    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)
    return data


def download_with_retry(url, logger, filepath, max_retries=3, request_timeout=30):
    """Download file with retry logic using curl for proper SSL certificate verification.
    
    Uses curl instead of requests to avoid Python 3.13 SSL certificate issues on macOS.
    curl uses the system's certificate store which is properly configured.
    """
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Downloading {url} (attempt {attempt + 1}/{max_retries})")
            
            # Use curl with system certificates (which works on macOS)
            result = subprocess.run(
                ['curl', '-f', '-L', '--max-time', str(request_timeout), '-o', filepath, url],
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Successfully downloaded {filepath}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.warning(f"Download attempt {attempt + 1} failed: {e.stderr}")
            if attempt == max_retries - 1:
                logger.error(f"Failed to download {url} after {max_retries} attempts")
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
    return False

def set_up_logger(logger_name, log_file=None, level=logging.INFO):
    if log_file is None:
        log_file = logs_dir() / f"{logger_name}.log"
    log_file = Path(log_file)
    ensure_dir(log_file.parent)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file)
        ]
    )
    logger = logging.getLogger(logger_name)

    return logger

def get_single_aopwiki_url(entity_id, page_type, page_anchor=None):
    wiki_base_url = "https://aopwiki.org"
    if page_anchor:
        return f"{wiki_base_url}/{page_type}/{entity_id}/#{page_anchor}"
    else:
        return f"{wiki_base_url}/{page_type}/{entity_id}"

def get_aopwiki_urls(entity_ids, page_type, page_anchor=None):
    wiki_urls_for_skipped_aops = {}

    for id in entity_ids:
        wiki_urls_for_skipped_aops[id] = get_single_aopwiki_url(id, page_type, page_anchor)
    
    return wiki_urls_for_skipped_aops

def format_elapsed(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"