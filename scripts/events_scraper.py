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
    'url': 'url',                        # includes URL fragment for event.
    'retracted': 'retracted',            # boolean
    'event type': 'type',                # currently only "Power Reactor"
    'event number': 'event_number',      # int
    'facility': 'facility',
    'region': 'region',                  # not stored
    'state': 'state',                    # not stored
    'unit': 'unit',                      # list of ints
    'rx type': 'rx_type',                # not stored. (appears in html events)
    'rxtype': 'rx_type',                 # not stored. (appears in text events)
    'nrc notified by': 'nrc_notified_by',
    'hq ops officer': 'hq_ops_officer',
    'emergency class': 'emergency',      # text, though might change
    '10 cfr section': 'cfr10_sections',  # list of tuples (section, name)
    'notification date': 'report_date',  # datetime object
    'notification time': 'report_time',  # merged with report_date
    'event date': 'event_date',          # datetime object
    'event time': 'event_time',          # merged with event_date
    'last update date': 'update_date',   # date object
    'person (organization)': 'people',   # list of tuples (person, organization)
    'reactor status': 'reactor_status',  # list of dicts. see REACTOR_STATUS_FIELDS
    'scram code': 'scram',               # text, though might change
    'rx crit': 'critical',               # boolean
    'initial pwr': 'initial_power',      # int
    'initial rx mode': 'initial_mode',
    'current pwr': 'current_power',      # int
    'current rx mode': 'current_mode',
    'subject': 'subject',
    'event text': 'body',                # list of strings, one per paragraph
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
        url_date = url.split('/')[-1].replace('en.html', '')
        # Magic date: August 15, 2003 is the last day to use text reports.
        if int(url_date) <= 20030815:
            events = parse_event_page_text(url)
        else:
            events = parse_event_page_html(url)
        pages_seen += 1
        events_seen += len(events)
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

def parse_event_page_html(url):
    parsed = parser_open(url)
    events = []
    # Each event entry on the page starts with an anchor named after the event
    # number. Pick out those anchors as a starting point for parsing.
    for anchor in parsed('a', attrs={'name': re.compile(r'^en\d+')}):
        event = init_event(url + '#' + anchor['name'])
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
        parse_event_fields(event, meta_cells[2].stripped_strings)
        res = re.match(r'(\d+)\s+State:\s+(\w+)', event['region'], flags=re.U)
        event['region'], event['state'] = res.groups()
        # Fourth cell also contains lines of text, always one field per line.
        parse_event_fields(event, meta_cells[3].stripped_strings)
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
    
def parse_event_page_text(url):
    parsed = parser_open(url)
    events = []
    # The HTML of these pages is only a wrapper around text-based reports,
    # all contained in a single PRE tag. The reports are in ASCII tables
    # and wrapped to exactly 80 columns.
    raw = parsed.find("pre").strings.next()
    if "Nuclear Regulatory Commission\n\n" in raw:
        # For some reason reports from 2003 have double newlines. Use the
        # NRC header to detect this and remove the extra newlines.
        lines = raw.split("\n\n")
    else:
        lines = raw.split("\n")
    # Start by splitting the blob into individual reports.
    reports = _text_split_reports(_text_preprocess(lines))
    for report in reports:
        event = init_event(url)
        # Retracted events will have an extra line at the beginning.
        # Remove that line if it's present.
        if 'RETRACTED' in report[0]:
            event['retracted'] = True
            report.pop(0)
        # First line will be a separator, and second line will have the
        # event type. We only care about Power Reactor events.
        res = re.match(r'\|([A-Za-z ]+?)\s+\|Event Number:\s*(\d+)', report[1], re.U)
        event_type, event_num = res.groups()
        if event_type != 'Power Reactor':
            continue
        event['type'] = event_type
        event['event_number'] = event_num
        # Strip off the starting separator lines (plus the just parsed line)
        # because the number of lines seems to vary between reports. Removing
        # them makes the other line numbers more consistent.
        report.pop(1)
        while report[0][0] == '+':
            report.pop(0)
        # It looks like the header region of a report is a fixed number of
        # lines. Unless this assertion shows otherwise, I'm going to assume
        # it is for the purpose of parsing.
        assert 'EVENT TEXT' in report[20]
        # Two of the lines have two fields, so they have to be reparsed.
        # This covers facility, unit, rxtype, nrc notified by, hq ops officer,
        # and emergency class.
        parse_event_fields(event, _text_get_column(report[0:8], 0))
        res = re.match(r'([A-Za-z ]+?)\s*REGION:\s+(\d+)', event['facility'], flags=re.U)
        event['facility'], event['region'] = res.groups()
        res = re.match(r'([][0-9 ]+?)\s{2,}STATE:\s+(\w+)', event['unit'], flags=re.U)
        event['unit'], event['state'] = res.groups()
        # Timestamps are in the second column on lines 4-8.
        parse_event_fields(event, _text_get_column(report[0:5], 1))
        # Lines 10-16, second column has related people. Skip first line
        # because it's the header.
        event['people'] = []
        for p in _text_get_column(report[7:13], 1):
            parts = re.split(r'(?u)\s{2,}', p, 1)
            # If only one column is given (e.g. the person is "FEMA"), then add
            # a second empty element to the list, since that's what happens in
            # the html parser.
            if len(parts) == 1:
                parts.append(None)
            event['people'].append(parts)
        # Lines 12-16, first column has the related CFR10 sections. First
        # line is header. There's nothing good to split the line on, so
        # I'm relying on them to be fixed-width fields.
        event['cfr10_sections'] = [
            (s[0:25].strip(), s[25:].strip())
            for s in _text_get_column(report[9:13], 0)]
        # Lines 20-22 has status information about each affected reactor.
        event['reactor_status'] = []
        for row in report[16:19]:
            # Parse into columns: unit, scram code, rx crit, init pwr,
            # init rx mode, curr pwr, curr rx mode.
            res = re.match(r'\|(\d+)\s+([A-Za-z/]+)\s+(\w+)\s+(\d+)\s+([A-Za-z ]+)\s*\|(\d+)\s+([A-Za-z ]+)\s+\|', row, re.U)
            if res:
                unit = dict(zip(REACTOR_STATUS_FIELDS, [f.strip() for f in res.groups()]))
                event['reactor_status'].append(unit)
        # Event text is line 26 to the end. Need to trim off the edges and
        # join lines into paragraphs.
        body = []
        prev_line = ""
        for line in report[22:-1]:
            line = line.strip("| ")
            if prev_line:
                body[-1] = body[-1] + " " + line
            elif line:
                body.append(line)
            prev_line = line
        # Now that lines are joined into paragraphs, remove the first and
        # treat it as the subject.
        event['subject'] = body.pop(0)
        event['body'] = body

        # All fields have been extracted from the source document, but all data
        # is a string. Convert fields to other types as appropriate.
        process_event(event)

        # Done. Record the event.
        events.append(event)
    return events

def _text_preprocess(lines):
    """ Cleans up odd formatting in some of the text reports. """
    idx = 0
    processed = []
    while idx < len(lines):
        cur = lines[idx]
        try:
            peek = lines[idx + 1]
        except IndexError:
            peek = None
        new = None
        # Some pages use a single period or form feed where others would have
        # a blank line in between reports.
        if cur == '.' or cur == "\x0C":
            new = ''
        # Reports marked as not for distribution sound tantalizing but appear
        # to be junk. Strip off the lines so they don't confuse the parser.
        elif 'NOT FOR PUBLIC DISTRIBUTION' in cur:
            pass
        # Some pages have incorrect line breaks. What would otherwise be an
        # 80-column table line gets split across two lines. Detect this by
        # looking for a short line that starts with a pipe and is followed by
        # another short line without a starting pipe.
        elif 1 < len(cur) < 80 and cur[0] == '|' and peek is not None \
             and ((len(peek) == 1 and peek == '|') \
                  or (1 < len(peek) < 80 and peek[0] != '|') \
                 ):
            # I think the lines always need a space added between them to get 80.
            assert len(cur) + len(peek) == 79
            new = cur + ' ' + peek
            # Advance current line an extra time.
            idx = idx + 1
        else:
            new = cur
        if new is not None:
            processed.append(new)
        idx = idx + 1
    return processed

def _text_split_reports(lines):
    # Scan for event numbers, then backing up a few lines and taking
    # everything down to the next number or the end of the list.
    reports = []
    current = None
    last_blank = 0
    for idx, line in enumerate(lines):
        # Record position of blank line but don't do anything with it.
        if not line.strip():
            last_blank = idx
            continue
        # Check whether this line is near the start of a new report.
        if re.match(r'^\|[^|]+\|Event Number:\s*\d+', line, re.U):
            # The event number appears a few lines farther down than
            # where we actually want to start capturing, so we both
            # have to backtrack to get the start of the report and
            # have to remove the lines from the previous report.
            if current:
                back = idx - last_blank - 1
                del current[back*-1:]
                # Save the now complete report.
                reports.append(current)
            # Start a new current report using the backtracked lines.
            # The current line will be added below.
            current = lines[last_blank+1:idx]
        if current:
            current.append(line)
    # Save the last report.
    if current:
        reports.append(current)
    return reports

def _text_get_column(lines, column):
    """ Extracts a column from a series of lines in a text-based table.
        Assumes the table is created with "|+-" characters. The column
        index starts at zero. """
    result = []
    for line in lines:
        cols = re.split(r'\||\+', line.strip('|+'))
        col = cols[column].strip()
        # Skip lines that are only row separator.
        if re.match(r'[^-]', col, re.U):
            result.append(col)
    return result

def init_event(url):
    event = {
        'url': url,
        'retracted': False,
        'crawl_time': datetime.datetime.now(TIMEZONES['UTC']),
    }
    return event

def parse_event_fields(event, lines):
    """ Parse rows of colon-separated key/value pairs and add them to the
        event dictionary using REPORT_FIELDS to map the names. """
    for line in lines:
        res = re.split(r'(?u):\s*', line, 1)
        if res[0].lower() in REPORT_FIELDS:
            event[REPORT_FIELDS[res[0].lower()]] = res[1]

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
            stale = True
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
    """ Add support for datetime objects to the JSON serializer. """
    if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
        return obj.isoformat()
    return obj

if __name__ == "__main__":
  sys.exit(main(sys.argv))