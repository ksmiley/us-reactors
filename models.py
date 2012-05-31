from django.db import models
from django.contrib.localflavor.us import us_states

# Most of these definitions come from the NRC's data dictionary for the
# reactor dataset. However several were missing and I had to fill them in
# from various sources.
# http://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr1350/app-datadictionary.xls   
NRC_REGIONS = (
    (1, 'Region 1'),
    (2, 'Region 2'),
    (3, 'Region 3'),
    (4, 'Region 4'),
)
# All current reactors use one of two possible design types. All BWR were
# made by GE.
REACTOR_TYPES = (
    ('BWR', 'boiling-water reactor'),
    ('PWR', 'pressurized-water reactor'),
)
# Design of the vessel that keeps radiation from reaching the outside world.
# The three "Mark" types apply only to BWR, while the the others
# apply only to PWR.
CONTAINMENT_TYPES = (
    ('MARK 1', 'BWR wet, Mark I'),
    ('MARK 2', 'BWR wet, Mark II'),
    ('MARK 3', 'BWR wet, Mark III'),
    ('DRYAMB', 'PWR dry, ambient pressure'),
    ('DRYSUB', 'PWR dry, subatmospheric pressure'),
    ('ICECND', 'PWR wet, ice condenser'),
)
# Who designed the reactor system. NRC calls this the Nuclear Steam System
# Supplier (NSSS).
VENDORS = (
    ('GE', 'General Electric'),
    ('B&W', 'Babcock & Wilcox'),
    ('CE', 'Combustion Engineering'),
    ('WEST', 'Westinghouse Electric'),
)
# The specific Nuclear Steam System design used at the site.
MODELS = (
    ('B&W LLP', 'B&W Lowered Loop'),
    # Apparently there were two types of reactors designed by CE, but the
    # first doesn't have any designation that I've been able to find.
    # Annoyingly the first is referred to as either "CE" or "COMB CE" in
    # the data, and the second is either "CE80-2L" or "COMB CE80-2L".
    ('CE', 'Combustion Engineering'),   
    ('CE80-2L', 'Combustion Engineering System 80'),
    ('GE 1', 'GE Type 1'),
    ('GE 2', 'GE Type 2'),
    ('GE 3', 'GE Type 3'),
    ('GE 4', 'GE Type 4'),
    ('GE 5', 'GE Type 5'),
    ('GE 6', 'GE Type 6'),
    ('WEST 2LP', 'Westinghouse Two-Loop'),
    ('WEST 3LP', 'Westinghouse Three-Loop'),
    ('WEST 4LP', 'Westinghouse Four-Loop'),
)
# Used for both Architect-Engineer and Constructor fields because there's
# so much overlap. Several of these are referred to in the dataset but not
# in the dictionary so they've been filled in from research. Note that
# "contractor" might not be the best term because it varies by site. For
# example, Duke Energy and TVA both are usually the operator, engineer, and
# builder of their plants.
# TODO add sources for ones missing from NRC dictionary
CONTRACTORS = (
    ('AEP', 'American Electric Power'),
    ('BALD', 'Baldwin Associates'),
    ('BECH', 'Bechtel'),
    ('BRRT', 'Brown & Root'),   # also B&R in source files
    ('CWE', 'Commonwealth Edison Company'),
    ('DANI', 'Daniel International'),
    ('DBDB', 'Duke & Bechtel'),
    ('DUKE', 'Duke Power Company'),
    ('EBSO', 'Ebasco'),
    ('FLUR', 'Fluor Pioneer'),
    ('G&H', 'Gibbs & Hill'),
    ('GHDR', 'Gibbs & Hill & Durham & Richardson'),
    ('GIL', 'Gilbert Associates'),
    ('GPC', 'Georgia Power Company'),
    ('JONES', 'J.A. Jones'),
    ('KAIS', 'Kaiser Engineers'),
    ('NIAG', 'Niagara Mohawk Power Corporation'),
    ('NSP', 'Northern States Power Company'),
    ('PG&E', 'Pacific Gas & Electric Company'),
    ('PSE', 'Pioneer Services & Engineering'),
    ('PUBS', 'Public Service Electric & Gas Company'),
    ('S&L', 'Sargent & Lundy'),
    ('S&W', 'Stone & Webster'),
    ('SBEC', 'Southern Services and Bechtel'),
    ('SSI', 'Southern Services Incorporated'),
    ('TVA', 'Tennessee Valley Authority'),
    ('UE&C', 'United Engineers & Constructors'),
    # Based on http://openjurist.org/202/f3d/530/carrie-v-new
    ('WDCO', 'WEDCO Corporation'),
)

class Facility(models.Model):
    """ A location with one or more reactors in close proximity. NRC data
    doesn't represent the data this way (they seem to consider each reactor
    individually), but it better matches how people think about a nuclear
    power plant.
    
    NRC does sometimes use "plant" to refer to a facility that has reactors.
    
    """
    name = models.CharField("site name", unique=True, max_length=75)
    short_name = models.CharField("short site name", unique=True, max_length=50)
    city = models.CharField(max_length=50)
    state = models.CharField(max_length=2, choices=us_states.US_STATES)
    region = models.IntegerField('NRC region', choices=NRC_REGIONS)
    operator = models.CharField(max_length=75)
    
    def __unicode__(self):
        return self.name
        
    class Meta:
        verbose_name_plural = "facilities"

class Reactor(models.Model):
    """ Information about a power-generating reactor. """
    unit = models.IntegerField("unit number")
    nrc_id = models.IntegerField("NRC docket number", unique=True)
    nrc_url = models.URLField("NRC information page")
    wiki_url = models.URLField("Wikipedia page", blank=True)
    nrc_photo = models.URLField("NRC photo URL")
    type = models.CharField("reactor type", max_length=3, choices=REACTOR_TYPES)
    containment = models.CharField("containment type", max_length=6, choices=CONTAINMENT_TYPES)
    vendor = models.CharField('reactor vendor', max_length=4, choices=VENDORS)
    model = models.CharField('reactor model', max_length=8, choices=MODELS)
    engineer = models.CharField('architect and engineer', max_length=5, choices=CONTRACTORS)
    constructor = models.CharField('constructor', max_length=5, choices=CONTRACTORS)
    permit_issued_on = models.DateField("construction permit issued")
    license_issued_on = models.DateField("operating license issued")
    operational_on = models.DateField("commercial operation started")
    license_renewed_on = models.DateField("renewed operating license issued", blank=True, null=True)
    license_expires_on = models.DateField("operating license expires")
    capacity = models.FloatField("production capacity (MWe)")
    thermal_capacity = models.FloatField("licensed thermal capacity (MWt)")
    active = models.BooleanField("operational", default=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    facility = models.ForeignKey(Facility)

    @property
    def title(self):
        if self.unit:
            return self.facility.name + ', Unit ' + unicode(self.unit)
        else:
            return self.facility.name

    @property
    def short_title(self):
        if self.unit:
            return self.facility.short_name + ' ' + unicode(self.unit)
        else:
            return self.facility.short_name
    
    def __unicode__(self):
        return self.short_title

class EventNotification(models.Model):
    """ Contents of an event notification report. """
    event_num = models.IntegerField("NRC event number", unique=True)
    url = models.URLField("report source")
    subject = models.CharField("report subject", max_length=255)
    body = models.TextField()
    emergency_status = models.CharField("emergency status", max_length=25)
    report_time = models.DateTimeField("report submitted at")
    event_time = models.DateTimeField("event time")
    update_date = models.DateField("report last updated")   # TODO might change to DateTime
    crawl_time = models.DateTimeField("report retrieved from NRC")
    retracted = models.BooleanField(default=False)
    reactors = models.ManyToManyField(Reactor, through='EventReactorStatus')
    facility = models.ForeignKey(Facility)
    cfr_sections = models.ManyToManyField('CFRSection')
    people = models.ManyToManyField('EventPerson')
    # TODO these two fields also include people's names, but need to do more
    # research to see if they can be stored in EventPerson
    nrc_notified_by = models.CharField(max_length=100)
    hq_ops_officer = models.CharField(max_length=100)
    # TODO people, nrc_notified_by, hq_ops_officer, cfr10_sections
    
    def __unicode__(self):
        return self.subject

class EventReactorStatus(models.Model):
    """ Connects reactors involved in an event to the report record, along
    with the status of each reactor. """
    event = models.ForeignKey(EventNotification)
    reactor = models.ForeignKey(Reactor)
    critical = models.BooleanField("reactor is critical")
    # TODO figure out possible scram codes. so far I've seen "N", "A/R" and "M/R".
    # I assume those are no, automatic, and manual.
    scram = models.CharField('SCRAM code', max_length=3)
    inital_mode = models.CharField("pre-event operation mode", max_length=25)
    current_mode = models.CharField("post-event operation mode", max_length=25)
    initial_power = models.IntegerField("pre-event power level")
    current_power = models.IntegerField("post-event power level")
    
    def __unicode__(self):
        return "Event " + unicode(self.event.event_num) + " at " + self.reactor.short_title

class EventPerson(models.Model):
    """ A person associated with an event notification. """
    name = models.CharField(max_length=100)
    organization = models.CharField(max_length=100)

    def __unicode__(self):
        return self.name + ", " + self.organization

class CFRSection(models.Model):
    """ Sections in the Code of Federal Regulations, Title 10, Chapter 1 (CFR10)
    that apply to an event notification.
    
    """
    section = models.CharField("CFR10 section", max_length=50)
    title = models.CharField(max_length=50)
    
    def __unicode__(self):
        return self.section + ' ' + self.title