# Data Cleanup Notes

[NRC Open Government](http://www.nrc.gov/public-involve/open.html) page has links to the base data, but it has to be cleaned up and augmented.

## Facilities and Reactors

Operating reactors as Excel file: http://www.nrc.gov/reading-rm/doc-collections/nuregs/staff/sr1350/appa.xls

XML file with some additional info about reactors, especially geographic coordinates and capacity ratings: http://www.nrc.gov/admin/data/gmaps/operatingreactors.xml
(This file is used to populate the map at http://www.nrc.gov/info-finder/reactor/ but is handy by itself.)

Cleanup required for Excel file:
 * Excel 2008 for Mac appears to be unable to export a CSV file with a usable character encoding, so don't use it. Google Docs is a better option.
 * Create a new Google Spreadsheet, then import the file with the option to replace the existing spreadsheet. (Importing this way instead of directly uploading might be required to get characters encoding correct, I'm not entirely sure.)
 * Search for "Tenessee" (note only one 'n'), replace with "Tennessee"
 * Select all cells with dates (columns K through O) and change date formatting to MM/DD/YYYY
 * Download from Google Docs as CSV.
 * Delete the first line from the file (the one before the header)

Cleanup required for XML file:
 * Find section for Indian Point Unit 3. Currently the docket number (id attribute) in the file is a duplicate of Unit 2. Change it to 05000286.
 * Find section for LaSalle Unit 1. Currenly the docket number is for a different plant. Change it to 05000373.
Two optional steps (fields that are wrong but are ignored by the loader):
 * Find McGuire Nuclear Station, Unit 2. Notice the short name (statustitle tag) says McGuire 1.
 * Find Quad Cities Nuclear Power Station, Unit 2. As above, its short name has it as Unit 1.

Run the XML through the `reactors_xml2csv.py` script and redirect to a temporary file.
Run `csvjoin -c 'Docket  Number,docket' data/operating-reactors.csv data/reactors_more.csv` where the first file was the one from Excel and the second was the one from XML. Cleanup the field names by piping through sed:
`sed -E '1,1{s/  +/ /;s/ +,/,/g;}'`

Redirect to a final merged file.

Pass that filename as the first argument to the `load_reactors.py` script, which will create facility and reactor records for each input row.