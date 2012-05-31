#!/usr/bin/python

import sys
import re
import datetime

import csvkit

from us_reactors.models import Facility, Reactor, VENDORS

def main(argv):
    try:
        raw_in = open(argv[1], 'rb')
    except IndexError:
        print "usage: %s csvfile" % (argv[0])
        return 1
    except IOError as e:
        print "Error opening %s: %s" %(argv[1], e.strerror)
        return 1
    csv_in = csvkit.CSVKitDictReader(raw_in)
    for record in csv_in:
        print "%s: %s" % (record['docket'], record['NRC Reactor Unit Web Page'])
        r = load_reactor(record)
        print "-> saved as %d" % (r.id)

def load_reactor(record):
    plant = find_facility(record)
    r = Reactor()
    # A few facilities have only one reactor and don't include a numbered unit.
    name, unit = parse_name(record['Plant Name, Unit Number'])
    r.name = name
    r.unit = unit if unit else 0
    r.nrc_id = int(record['docket'])
    r.nrc_url = record['nrc_url']
    r.nrc_photo = record['nrc_photo']
    r.type, r.containment = record['Reactor and Containment Type'].split('-')
    # Vendor and model are derived from the same column. Requires some cleanup
    # because Combustion Engineering models are stored weird.
    model_raw = record['Nuclear Steam System Supplier and Design Type']
    if model_raw.startswith('COMB'):
        model_raw = model_raw.replace('COMB ', '')
    r.model = model_raw
    for vendor_code, vendor_name in VENDORS:
        if vendor_code in model_raw:
            r.vendor = vendor_code
            break
    r.engineer = record['Architect-Engineer']
    # Not a typo. Field name is spelled wrong in data.
    r.constructor = record['Contructor']
    r.permit_issued_on = parse_date(record['Construction Permit Issued'])
    r.license_issued_on = parse_date(record['Operating License Issued'])
    r.operational_on = parse_date(record['Commercial Operation'])
    if record['Renewed Operating License Issued']:
        r.license_renewed_on = parse_date(record['Renewed Operating License Issued'])
    r.license_expires_on = parse_date(record['Operating License Expires'])
    r.capacity = float(record['capacity'])
    r.thermal_capacity = float(record['Licensed MWt'])
    r.active = True
    r.latitude = float(record['latitude'])
    r.longitude = float(record['longitude'])
    r.facility = plant
    r.save()
    return r

def find_facility(record):
    """ Lookup the Facility object associated with an input row. Creates the
    Facility record in the database if it doesn't exist yet.
    
    """
    name = parse_short_name(record['NRC Reactor Unit Web Page'])[0]
    try:
        facility = Facility.objects.get(short_name=name)
        return facility
    except Facility.DoesNotExist:
        # Create the Facility record using the data row.
        return load_facility(record)

def load_facility(record):
    f = Facility()
    # Ignore the unit number returned by with both names.
    f.name = parse_name(record['Plant Name, Unit Number'])[0]
    f.short_name = parse_short_name(record['NRC Reactor Unit Web Page'])[0]
    # City and state are in a field that also includes the relative distance
    # to the nearest larger city. Needless to say that data can be ignored.
    # Some rows are formatted wrong, such as not capitalizing both letters in
    # the state code or using a period instead of a comma.
    parts = re.match(r'(.+?)[,.]\s+(\w{2})\s?\(', record['Location'])
    f.city = parts.group(1)
    f.state = parts.group(2).upper()
    f.region = int(record['NRC Region'])
    f.operator = record['Licensee']
    f.save()
    return f

def parse_name(raw):
    """ Takes a string like "Vogtle Electric Generating Plant, Unit 1" and
    returns a tuple with the name (Vogtle Electric Generating Plant) and
    unit number (1). If the string doesn't include a unit number, returns
    the input as the name and None for the unit.
    
    """
    parts = re.match(r'(.+), Unit\s+(\d)', raw)
    if parts:
        name = parts.group(1)
        unit = int(parts.group(2))
        return name, unit
    else:
        return raw, None

def parse_short_name(raw):
    """ Takes a string like "Vogtle 1" and returns a tuple with the
    short name (Vogtle) and unit number (1). If the string doesn't
    include a unit number, returns the input as the name and None for
    the unit.
    
    """
    parts = re.match(r'(.+) (\d)', raw)
    if parts:
        name = parts.group(1)
        unit = int(parts.group(2))
        return name, unit
    else:
        return raw, None

def parse_date(date_str):
    """ Create date object from a string in M/D/YYYY format. """
    try:
        month, day, year = [int(p) for p in date_str.split('/')]
    except ValueError:
        return None
    # Handle two-year dates by treating everything above 60 as 20th century.
    if year < 100:
        if year > 60:
            year += 1900
        else:
            year += 2000
    return datetime.date(year, month, day)

if __name__ == "__main__":
  sys.exit(main(sys.argv))
