#!/usr/bin/python

# TODO:
# parse retraction and update notes out of body, since they seem to be
#   deleneated fairly consistently. also, use the subject line of those to 
#   extract a retraction or update time (since the fielded update is only a 
#   date)

import sys
import re
import json
import urllib2
import urlparse
import datetime
from time import sleep

import pprint

import dateutil.parser
import dateutil.tz
from bs4 import BeautifulSoup
from bs4.element import Comment


PAGE_CACHE_BASE = "/Users/keith/scratch/reactors/raw/"
PARSED_EVENTS_BASE = "/Users/keith/scratch/reactors/events/"

EVENT_INDEX_URL_TMPL = "http://www.nrc.gov/reading-rm/doc-collections/event-status/event/%d/"
#EVENT_INDEX_YEARS = range(1999, 2013)
EVENT_INDEX_YEARS = [2012]

# Translate field labels used in original report to internal names.
# All fields are parsed and stored as strings, unless otherwise noted.
REPORT_FIELDS = {
    'URL': 'url',                        # includes URL fragment for event.
    'Retracted': 'retracted',            # boolean
    'Event Type': 'type',                # currently only "Power Reactor"
    'Event Number': 'event_number',      # int
    'Facility': 'facility',
    'Region': 'region',                  # not stored
    'State': 'state',                    # not stored
    'Unit': 'unit',                      # list of ints
    'RX Type': 'rx_type',                # not stored
    'NRC Notified By': 'nrc_notified_by',
    'HQ OPS Officer': 'hq_ops_officer',
    'Emergency Class': 'emergency',      # text, though might change
    '10 CFR Section': 'cfr10_sections',  # list of tuples (section, name)
    'Notification Date': 'report_date',  # datetime object
    'Notification Time': 'report_time',  # merged with report_date
    'Event Date': 'event_date',          # datetime object
    'Event Time': 'event_time',          # merged with event_date
    'Last Update Date': 'update_date',   # date object
    'Person (Organization)': 'people',   # list of tuples (person, organization)
    'Reactor Status': 'reactor_status',  # list of dicts. see REACTOR_STATUS_FIELDS
    'SCRAM Code': 'scram',               # text, though might change
    'RX CRIT': 'critical',               # boolean
    'Initial PWR': 'initial_power',      # int
    'Initial RX Mode': 'initial_mode',
    'Current PWR': 'current_power',      # int
    'Current RX Mode': 'current_mode',
    'Subject': 'subject',
    'Event Text': 'body',                # list of strings, one per paragraph
    }
# Internal column names for the reactor status table.
REACTOR_STATUS_FIELDS = [
    'unit', 'scram', 'critical',
    'initial_power', 'initial_mode',
    'current_power', 'current_mode',
    ]

# Set up timezones list for parsing dates. Only have to consider the lower 48
# states because there are no reactors in Alaska or Hawaii. However, there is
# a reactor in Arizona that requires special handling because the state does not
# observe daylight saving time. It's the only reactor in the Mountain timezone, 
# so we could cheat and pretend MDT doesn't exist. Instead though we'll make
# fake timezone abbreviation for the state and handle it in the parser.
# (Note: If the scope of this code is ever expanded, even this might not be
# enough of a hack because the Navajo Nation is geographically within AZ and
# _does_ observe DST.)
TIMEZONES = {
    'UTC': dateutil.tz.tzutc(),
    'EST': dateutil.tz.gettz('EST5EDT'),
    'CST': dateutil.tz.gettz('CST6CDT'),
    'MST': dateutil.tz.gettz('MST7MDT'),
    'PST': dateutil.tz.gettz('PST8PDT'),
    'AZMST': dateutil.tz.gettz('America/Phoenix'),
}
TIMEZONES['ET'] = TIMEZONES['EST']
TIMEZONES['EDT'] = TIMEZONES['EST']
TIMEZONES['CDT'] = TIMEZONES['CST']
TIMEZONES['MDT'] = TIMEZONES['MST']
TIMEZONES['PDT'] = TIMEZONES['PST']


def main(argv=None):
    fetch_all(gather_page_urls(EVENT_INDEX_YEARS))

def fetch_all(urls):
    """ Loops over urls and downloads each page, then parses out individual 
    events and writes each to a JSON file.
    
    """
    pages_seen = events_seen = 0
    for url in urls:
        print url
        events = parse_event_page(url)
        pages_seen += 1
        events_seen += len(events)
        url_date = url.split('/')[-1].replace('en.html', '')
        for event in events:
            name_parts = [PARSED_EVENTS_BASE, str(event['event_number']), '-', url_date, '.json']
            print " > Event %d" % (event['event_number'])
            with open(''.join(name_parts), 'w') as f:
                json.dump(event, f, indent=4, default=freeze_time)
    print "Done. %d events on %d pages" % (events_seen, pages_seen)

def gather_page_urls(years):
    """ Retrieve the event digest pages for the given list of years and find
    URLs for all linked event pages. Generator that yields one URL per invocation.
    
    This is implemented as a generator to keep from blasting the server with
    requests for digest pages every time the script runs. Instead pages are 
    only requested right before they're used.
    
    """
    for year in years:
        digest_url = EVENT_INDEX_URL_TMPL % (year)
        # Parser returns a full list instead of an iterator so it doesn't have
        # to keep the full page content and parser object alive.
        page_urls = parse_event_digest(digest_url)
        for url in page_urls:
            yield url

def parse_event_digest(url):
    """ Finds all links to event pages on a year page and return a list of URLs.
    
    """
    parsed = parser_open(url)
    event_pages = []
    # Each event page is named with the date in "YYYYMMDDen.html" format. Pages
    # are only created for working days, so it's easier to parse the year pages
    # to get the links than it is to guess the page URLs and get a lot of 404s.
    for anchor in parsed('a', href=re.compile(r'^\d{8}en\.html$')):
        # Links are relative to current page and need to be made absolute.
        daily_url = urlparse.urljoin(url, anchor['href'])
        event_pages.append(daily_url)
    return event_pages

def parse_event_page(url):
    parsed = parser_open(url)
    events = []
    # Each event entry on the page starts with an anchor named after the event
    # number. Pick out those anchors as a starting point for parsing.
    for anchor in parsed('a', attrs={'name': re.compile(r'^en\d+')}):
        event = {
            'url': url + '#' + anchor['name'],
            'retracted': False,
            'crawl_time': datetime.datetime.now(TIMEZONES['UTC']),
        }
        # First table after the anchors contains various fields of metadata
        # about the event. The table is only use for layout; the actual fields
        # and data are just lines of text.
        meta_table = anchor.find_next_sibling('table')
        # Table contains three rows with two cells each. Since the table is
        # only for layout, grab all six cells (or seven for a retraction).
        meta_cells = meta_table('td')
        # First cell usually contains the type of event report. Retracted events
        # add another cell to the beginning, so check for retraction and shift
        # off that cell if found.
        if 'RETRACTED' in meta_cells[0].string:
            event['retracted'] = True
            meta_cells.pop(0)
        # Only look at "Power Reactor" reports.
        event_type = meta_cells[0].string
        if event_type != 'Power Reactor':
            continue
        event['type'] = event_type
        # Second cell has the unique number for this event report, and includes
        # a label that needs to be stripped off.
        event['event_number'] = meta_cells[1].string.replace('Event Number: ', '')
        # Third cell contains lines of text. Most lines have one field, except
        # one line has both region and state.
        for line in meta_cells[2].stripped_strings:
            res = re.split(r'(?u):\s*', line, 1)
            if res[0] in REPORT_FIELDS:
                event[REPORT_FIELDS[res[0]]] = res[1]
        res = re.match(r'(\d+)\s+State:\s+(\w+)', event['region'], flags=re.U)
        event['region'], event['state'] = res.groups()
        # Fourth cell also contains lines of text, always one field per line.
        for line in meta_cells[3].stripped_strings:
            res = re.split(r'(?u):\s*', line, 1)
            if res[0] in REPORT_FIELDS:
                event[REPORT_FIELDS[res[0]]] = res[1]
        # Fifth cell has two fields. The first ("Emergency Class") is on one
        # line, the second ("10 CFR Section") is split across multiple lines
        # and can list multiple sections.
        lines = list(meta_cells[4].stripped_strings)
        # Extract emergency status.
        event['emergency'] = lines[0].replace('Emergency Class: ', '')
        # List sections with number and names separated.
        event['cfr10_sections'] = [tuple(l.split(' - ')) for l in lines[2:]]
        # Sixth cell has one field ("Person (Organization)") on multiple lines.
        # The first line is the header, so just take every other line.
        # The organization is sometimes missing but the parenthesis are still
        # included (e.g. "PART 21 GROUP ()")
        people = list(meta_cells[5].stripped_strings)[1:]
        event['people'] = [
            re.match(r'(.+) \(([^)]*)\)', p, re.U).groups() 
            for p in people]        
        # Move to the second table, which has status information about each
        # reactor at the facility for before and after the event.
        rx_table = meta_table.find_next_sibling('table')
        rx_rows = rx_table('tr')
        event['reactor_status'] = []
        # Skip the header by starting with the second row.
        for row in rx_rows[1:]:
            values = [f.string for f in row('td')]
            unit = dict(zip(REACTOR_STATUS_FIELDS, values))
            event['reactor_status'].append(unit)

        # Move to the third table, which has a single cell holding the body
        # text. The text is separated by <br> tags, and the first line can
        # be considered the event subject.
        text_table = rx_table.find_next_sibling('table')
        all_text = text_table('td')[0].stripped_strings
        # all_text is a generator, so can't use list slicing
        event['subject'] = all_text.next()
        event['body'] = list(all_text)

        # All fields have been extracted from the source document, but all data
        # is a string. Convert fields to other types as appropriate.
        process_event(event)

        # Done. Record the event.
        events.append(event)
    return events

def process_event(event):
    event['event_number'] = int(event['event_number'])

    # Don't store the region, state, and reactor type fields because we have
    # that information in a separate database and can match based on the
    # Facility field. However, peek at the state code to see if this unit is 
    # in Arizona (see comments at the TIMEZONES declaration).
    use_dst = True
    if event['state'] == 'AZ':
        use_dst = False
    del event['region'], event['state'], event['rx_type']
        
    # Parse dates and times to native objects. update_date is easy because
    # there is no time component.
    # TODO usually the body of the report includes an update time that
    #      could probably be parsed out
    event['update_date'] = convert_time(event['update_date'])

    # Event timestamp is given local to the facility location, so timezones
    # have to be considered. The report timestmap is always Eastern timezone
    # because it's apparently relative to NRC headquarters. In both cases,
    # the converted datetime object is placed in the time field and the
    # original date field is discarded.
    event['event_time'] = convert_time(event['event_date'], 
                                       event['event_time'], use_dst)
    event['report_time'] = convert_time(event['report_date'],
                                        event['report_time'])
    del event['event_date'], event['report_date']

    # Process Unit field to get a list of reactors numbers involved in this
    # report instead of a string. The raw string is like "[1] [2] [ ]", where
    # the space within empty brackets is actually a non-breaking space (\xa0)
    # TODO merge this into the reactor status list
    affected = [int(u) for u in re.findall(r'\[(\d+)\]', event['unit'], re.U)]
    del event['unit']
    # Merge list of affected units into reactor status list. Convert various
    # numeric fields in the list to ints. The cirticla field appears to be
    # a flag, so it's cast to boolean.
    for unit in event['reactor_status']:
        unit['unit'] = int(unit['unit'])
        if unit['unit'] in affected:
            unit['affected'] = True
        else:
            unit['affected'] = False
        unit['initial_power'] = int(unit['initial_power'])
        unit['current_power'] = int(unit['current_power'])
        assert unit['critical'] == 'Y' or unit['critical'] == 'N'
        unit['critical'] = True if unit['critical'] == 'Y' else False
        
    
def convert_time(date_part, time_part=None, use_dst=True):
    """ Takes a date string and time string in local time and converts 
    to a datetime object in UTC.
    
    """
    # Check for a time component. Some events only have a date, but the time
    # field still has a timezone identifier in it. If there are no numbers 
    # in the time field, return a date-only object.
    if time_part and re.search(r'\d', time_part, re.U):
        # Combine date and time strings. Strip bracket from timezone because
        # they confuse the parser.
        time_str = date_part + ' ' + time_part.replace('[', '').replace(']', '')
        # Special timezone handling for Arizona (see note with TIMEZONES).
        if not use_dst and 'MST' in time_part:
            time_str = time_str.replace('MST', 'AZMST')
        time_obj = dateutil.parser.parse(time_str, tzinfos=TIMEZONES)
        return time_obj.astimezone(TIMEZONES['UTC'])
    else:
        time_obj = dateutil.parser.parse(date_part)
        return time_obj.date()

def parser_open(url):
    """ Fetch a URL and create a BeautifulSoup object from the response. Uses
    a rudimentary cache for pages, so the parser can be tested and run 
    repeatedly without constantly hitting NRC servers.
    
    """
    cacheable, stale, cache_name = False, False, ""
    page = None
    # Yearly digest pages, which don't end in .html, aren't cached.
    if PAGE_CACHE_BASE and url.endswith('html'):
        cacheable = True
        cache_name = url.split('/')[-1]
        # Try opening the cached file. If that fails, set a flag to download it.
        try:
            page = urllib2.urlopen('file://' + PAGE_CACHE_BASE + cache_name)
            print "(used cache)"
        except urllib2.URLError as e:
            stale = true
    # Fallback to downloading page.
    if stale or not cacheable:
        page = urllib2.urlopen(url)
        print "(hit server)"
        # Force delay between requests to take it easy on the server.
        sleep(0.25)
    body = page.read()
    # Cache event pages.
    if stale and cacheable:
        with open(PAGE_CACHE_BASE + cache_name, 'w') as f:
            f.write(body)
    # Specify html5lib because it seems to give best results. lxml had problems
    # with not closing <br> tags, so tables would get lost inside the line break
    # and no longer be siblings as expected.
    return BeautifulSoup(body, 'html5lib')

def freeze_time(obj):
    if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
        return obj.isoformat()
    return obj

if __name__ == "__main__":
  sys.exit(main(sys.argv))