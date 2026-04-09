#!/usr/bin/env python3
"""Convert ker_2937_evidence_map_2.html to CSV format"""

import csv
from bs4 import BeautifulSoup


def parse_observation(td):
    """Parse observation cell containing structured list data"""
    ul = td.find('ul')
    if not ul:
        return td.get_text(strip=True)
    
    data = {}
    for li in ul.find_all('li'):
        span = li.find('span')
        if span:
            field = span.get_text(':').strip().lower().replace(' ', '_')
            value = li.get_text().replace(span.get_text(), '').strip()
            data[field] = value
    
    return '; '.join(f"{k.replace('_', ' ').title()}: {v}" for k, v in data.items())


def convert_html_to_csv(html_file, csv_file):
    with open(html_file, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    
    table = soup.find('table')
    headers = [th.get_text(strip=True) for th in table.find('thead').find_all('th')]
    
    rows = []
    # Iterate through each table row in the body
    for tr in table.find('tbody').find_all('tr'):
        cells = tr.find_all('td')
        # For each cell, use parse_observation for columns 3-4 (Upstream/Downstream Observation)
        # which contain structured <ul> data, otherwise just extract plain text
        row = [parse_observation(cells[i]) if i in [3, 4] else cells[i].get_text(strip=True) 
               for i in range(len(cells))]
        rows.append(row)
    
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    
    print(f"Converted to {csv_file} ({len(rows)} rows)")


if __name__ == '__main__':
    convert_html_to_csv(
        "inputs/from_emod_prototypes/ker_2937_evidence_map_2.html",
        "outputs/tabulated_ker_evidence/ker_2937_evidence_map_2.csv"
    )
