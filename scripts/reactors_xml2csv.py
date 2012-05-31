#!/usr/bin/python

import sys

from lxml import etree
import csv

# Input from file, output to stdout
INPUT_FILE = "data/operatingreactors.xml"

HEADER_FIELDS = [u'docket', u'latitude', u'longitude', u'nrc_url', u'nrc_photo', u'capacity']

# lxml segfaults when I pass it the filename, so open it first
fin = open(INPUT_FILE)
source = etree.parse(fin)
converted = csv.writer(sys.stdout, HEADER_FIELDS)
# Fake writeheader() because my Python is outdated.
converted.writerow(HEADER_FIELDS)

for facility in source.findall('facility'):
    row = [
        int(facility.get('id')),
        # Latitude and longitude left as strings for now to maintain precision.
        facility.find('latitude').text,
        facility.find('longitude').text,
        'http://www.nrc.gov' + facility.find('url').text,
        'http://www.nrc.gov' + facility.find('photourl').text,
        float(facility.find('output').text.replace(' MWe', '')),
    ]
    converted.writerow(row)