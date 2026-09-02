from bs4 import BeautifulSoup
from html import unescape

# Helper functions for KERs
def collect_ker_to_aop_mapping_from_xml(root, xml_namespace, refs):
    """
    Build KER mapping directly from XML data.
    
    Extracts all AOPs and their associated KERs from the AOP-Wiki XML,
    creating a dictionary that maps each KER ID to a properties dictionary containing:
    - aop_ids: AOP IDs that include the KER
    - adjacency_types: adjacency labels from AOP relationship metadata
    - aop_to_adjacency_type_pairs: per-AOP adjacency mapping for the KER
    
    Args:
        root: ElementTree Element object (XML root)
        xml_namespace: XML namespace
        refs: Reference dictionaries for ID mapping

    Returns:
        tuple:
            - ker_to_aop_dict: Dictionary mapping KER IDs to properties dicts
            - aop_to_ker_list_dict: Dictionary mapping AOP IDs to lists of KER IDs
    """
    ker_to_aop_dict = {}
    aop_to_ker_list_dict = {}
    
    for aop in root.findall(xml_namespace + 'aop'):
        aop_id = refs['AOP'][aop.get('id')]
        aop_kers = aop.find(xml_namespace + 'key-event-relationships')
        
        if aop_kers is not None:
            for ker in aop_kers.findall(xml_namespace + 'relationship'):
                ker_id = refs['KER'][ker.get('id')]
                # Use set to automatically handle duplicate avoidance
                if ker_id not in ker_to_aop_dict:
                    ker_to_aop_dict[ker_id] = {
                        'aop_ids': set(),
                        'adjacency_types': set(),
                        'aop_to_adjacency_type_pairs': {}
                    }

                ker_to_aop_dict[ker_id]['aop_ids'].add(aop_id)
                aop_to_ker_list_dict.setdefault(aop_id, set()).add(ker_id)

                adjacency_elem = ker.find(xml_namespace + 'adjacency')
                adjacency_value = adjacency_elem.text.strip() if adjacency_elem is not None and adjacency_elem.text else None
                if adjacency_value:
                    ker_to_aop_dict[ker_id]['adjacency_types'].add(adjacency_value)
                    ker_to_aop_dict[ker_id]['aop_to_adjacency_type_pairs'][aop_id] = adjacency_value
    
    # Convert sets to lists for consistency
    ker_to_aop_dict = {
        ker_id: {
            'aop_ids': sorted(list(ker_props['aop_ids'])),
            'adjacency_types': sorted(list(ker_props['adjacency_types'])),
            'aop_to_adjacency_type_pairs': {
                aop_id: ker_props['aop_to_adjacency_type_pairs'][aop_id]
                for aop_id in sorted(ker_props['aop_to_adjacency_type_pairs'])
            },
        }
        for ker_id, ker_props in ker_to_aop_dict.items()
    }
    aop_to_ker_list_dict = {k: list(v) for k, v in aop_to_ker_list_dict.items()}
    return ker_to_aop_dict, aop_to_ker_list_dict

def parse_evidence_tables(evidence_html):
    # Decode HTML entities so BeautifulSoup can find tables
    decoded_html = unescape(evidence_html)
    soup = BeautifulSoup(decoded_html, 'html.parser')
    tables = soup.find_all('table')
    parsed_tables = {}
    all_headers = []

    for index, table in enumerate(tables):
        headers = [th.get_text(strip=True) for th in table.find_all('th')]
        row_dicts = []
        trs = table.find_all('tr')
        # If no th elements, use first row's td as headers
        if headers == [] and trs:
            first_row_tds = trs[0].find_all('td')
            headers = [td.get_text(strip=True) for td in first_row_tds]
            data_rows = trs[1:]
        else:
            data_rows = trs

        for tr in data_rows:
            cells = [td.get_text(strip=True) for td in tr.find_all('td')]
            # Include rows even if cell count doesn't match headers - some cells may be empty or span multiple
            if cells:
                # Pad cells with empty strings if needed to match header count
                if len(cells) < len(headers):
                    cells = cells + [''] * (len(headers) - len(cells))
                # Truncate cells if they exceed header count
                elif len(cells) > len(headers):
                    cells = cells[:len(headers)]
                row_dict = dict(zip(headers, cells))
                row_dicts.append(row_dict)
        parsed_tables[index] = row_dicts
        all_headers.extend(headers)
    
    return parsed_tables, list(set(all_headers))

def collect_tables_from_field(field):
    """
    Collect tables from a field, returning both tables dict and headers list.
    Returns: (tables_dict, headers_list) tuple
    """
    tables_collected = {}
    headers = []
    if field is not None and field.text:
        if '&lt;table' in field.text or '<table' in field.text:
            tables, field_headers = parse_evidence_tables(field.text)
            if tables:
                tables_collected = tables
                headers = field_headers
    return tables_collected, headers
 