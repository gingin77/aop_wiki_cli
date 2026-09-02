# This script was intially based on code in the https://github.com/marvinm2/AOPWikiRDF project
from datetime import date
import os
import gzip
import shutil
import logging

from xml.etree.ElementTree import parse

from aop_wiki_cli.paths import ensure_dir, xml_inputs_dir
from aop_wiki_cli.utilities import download_with_retry, set_up_logger

AOPWIKI_XML_URL = 'https://aopwiki.org/downloads/aop-wiki-xml.gz'
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

# Session-level cache for parsed XML data (prevents redundant parsing)
_XML_CACHE = {}


def validate_xml_structure(root, expected_namespace, logger):
    """Validate basic XML structure."""
    if root is None:
        raise ValueError("XML root is None")
    
    if root.tag != expected_namespace + 'data':
        logger.warning(f"Unexpected root tag: {root.tag}")
    
    # Check for required vendor-specific section
    vendor_section = root.find(expected_namespace + 'vendor-specific')
    if vendor_section is None:
        raise ValueError("Missing vendor-specific section in XML")
    
    logger.info("XML structure validation passed")
    return True

def validate_entity_counts(refs, logger):
    """Validate that we have reasonable entity counts."""
    min_expected = {'AOP': 1, 'KE': 1, 'KER': 1, 'Stressor': 1}
    
    for entity_type, min_count in min_expected.items():
        actual_count = len(refs.get(entity_type, {}))
        if actual_count < min_count:
            logger.warning(f"Low count for {entity_type}: {actual_count} (expected >= {min_count})")
        else:
            logger.info(f"Entity count validation passed for {entity_type}: {actual_count}")
    
    return True

def extract_gzipped_xml(aopwikixmlfilename, filepath, logger):
    # Extract gzipped XML file
    try:
        with gzip.open(filepath + aopwikixmlfilename + '.gz', 'rb') as f_in:
            with open(filepath + aopwikixmlfilename, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        logger.info(f"Successfully extracted XML to {filepath + aopwikixmlfilename}")
    except (FileNotFoundError, gzip.BadGzipFile, IOError) as e:
        logger.error(f"Failed to extract XML file: {e}")

def collect_refs(root, xml_namespace):
    refs = {'AOP': {}, 'KE': {}, 'KER': {}, 'Stressor': {}}
    for ref in root.find(xml_namespace + 'vendor-specific').findall(xml_namespace + 'aop-reference'):
        refs['AOP'][ref.get('id')] = ref.get('aop-wiki-id')
    for ref in root.find(xml_namespace + 'vendor-specific').findall(xml_namespace + 'key-event-reference'):
        refs['KE'][ref.get('id')] = ref.get('aop-wiki-id')
    for ref in root.find(xml_namespace + 'vendor-specific').findall(xml_namespace + 'key-event-relationship-reference'):
        refs['KER'][ref.get('id')] = ref.get('aop-wiki-id')
    for ref in root.find(xml_namespace + 'vendor-specific').findall(xml_namespace + 'stressor-reference'):
        refs['Stressor'][ref.get('id')] = ref.get('aop-wiki-id')

    return refs


def check_for_aopwikixml(today, logger):
    """Check if today's AOP-Wiki XML exists; if not, download and extract it."""
    filepath = str(ensure_dir(xml_inputs_dir())) + os.sep
    aopwikixmlfilename = f'aop-wiki-xml-{today}'
    full_path = filepath + aopwikixmlfilename
    
    logger.info(f"Using data directory: {filepath}")
    
    if os.path.isfile(full_path):
        logger.info(f"AOP-Wiki XML file already exists: {full_path}")
        return full_path, False  # File exists, not freshly downloaded
    
    # Download and extract fresh XML
    logger.info(f"Starting AOP-Wiki XML extraction for date: {today}")
    filepath_gz = full_path + '.gz'
    download_with_retry(AOPWIKI_XML_URL, logger, filepath_gz)
    extract_gzipped_xml(aopwikixmlfilename, filepath, logger)
    
    return full_path, True  # Freshly downloaded


def parse_xml(xml_filepath, logger):
    """Parse XML file and return root element and namespace."""
    xml_namespace = '{http://www.aopkb.org/aop-xml}'
    
    try:
        tree = parse(xml_filepath)
        root = tree.getroot()
        if root is None or len(root) == 0:
            raise ValueError("XML file appears to be empty or invalid")
        logger.info(f'AOP-Wiki XML parsed successfully, contains {len(root)} entities')
    except Exception as e:
        logger.error(f"Failed to parse XML file: {e}")
        raise SystemExit(1)
    
    return root, xml_namespace


def validate_xml(root, xml_namespace, refs, logger):
    """Run structure and entity count validations on parsed XML."""
    # Validate XML structure (check root tag, required sections)
    try:
        validate_xml_structure(root, xml_namespace, logger)
    except ValueError as e:
        logger.error(f"XML structure validation failed: {e}")
        raise SystemExit(1)
    
    # Validate entity counts (ensure reasonable data)
    try:
        validate_entity_counts(refs, logger)
    except Exception as e:
        logger.error(f"Entity count validation failed: {e}")


def collect_xml_data(today):
    """
    Main entry point for XML data collection with session-level caching.
    
    Caches parsed XML data in memory to avoid redundant parsing within
    the same Python session. Cache is keyed by date.
    
    Workflow:
    1. Check if already cached for this date
    2. If cached, return cached data immediately
    3. If not cached:
       - Check if today's XML already exists locally
       - If not, download from AOP-Wiki and extract
       - Parse XML and collect entity refs
       - If freshly downloaded, run full validation
       - Cache and return root, namespace, and entity refs
    
    Args:
        today: Date object for the XML snapshot
        
    Returns:
        tuple: (root, xml_namespace, refs)
    """
    # Check cache first
    cache_key = str(today)
    if cache_key in _XML_CACHE:
        return _XML_CACHE[cache_key]
    
    logger = set_up_logger('aop-wiki-xml-extraction', level=logging.INFO)
    
    # Check cache / download if needed
    xml_filepath, is_fresh = check_for_aopwikixml(today, logger)
    
    # Parse XML
    root, xml_namespace = parse_xml(xml_filepath, logger)
    refs = collect_refs(root, xml_namespace)
    
    # Only validate fresh downloads
    if is_fresh:
        validate_xml(root, xml_namespace, refs, logger)
    
    # Cache the results
    result = (root, xml_namespace, refs)
    _XML_CACHE[cache_key] = result
    
    return result

if __name__ == "__main__":
    # Test caching functionality
    print("\n" + "="*60)
    print("Testing XML Data Collection and Caching")
    print("="*60)
    
    today = date.today()
    
    print(f"\nFirst call to collect_xml_data({today})...")
    root1, ns1, refs1 = collect_xml_data(today)
    print(f"✓ Collected: {len(list(root1))} root children, {len(refs1)} ref categories")
    print(f"  - AOPs: {len(refs1['AOP'])}")
    print(f"  - KEs: {len(refs1['KE'])}")
    print(f"  - KERs: {len(refs1['KER'])}")
    print(f"  - Stressors: {len(refs1['Stressor'])}")
    
    print(f"\nSecond call to collect_xml_data({today})...")
    print("(Should return cached data without re-parsing)")
    root2, ns2, refs2 = collect_xml_data(today)
    print(f"✓ Retrieved from cache")
    
    print("\nVerifying cache effectiveness:")
    print(f"  - Same root object: {root1 is root2}")
    print(f"  - Same namespace: {ns1 == ns2}")
    print(f"  - Same refs object: {refs1 is refs2}")
    
    print("\n" + "="*60)
    print("✓ Cache test complete")
    print("="*60 + "\n")
