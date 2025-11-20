import requests
from bs4 import BeautifulSoup
import csv
import re
import os
from datetime import datetime
import uuid

def sanitize_filename(s):
    """
    Sanitize the summary text to create a safe filename.
    """
    return re.sub(r'[^\w\-_\. ]', '_', s).strip().replace(" ", "_")

def format_date(date_str):
    """
    Convert a date string from formats like "Feb 18, 2025" to "MM/DD/YYYY".
    If parsing fails, return the original string.
    """
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%m/%d/%Y")
        except ValueError:
            continue
    return date_str

def parse_single_range(date_str):
    """
    Parse a single range date string like "Feb 18 – 20, 2025"
    and return (start_date, end_date) in the original string format.
    If no hyphen is found, returns the same date for both.
    """
    parts = re.split(r'\s*[–-]\s*', date_str)
    if len(parts) == 1:
        # No range found; use same date for start and end.
        return date_str.strip(), date_str.strip()
    elif len(parts) == 2:
        left = parts[0].strip()
        right = parts[1].strip()
        # Patterns to find month abbreviations and year.
        month_regex = r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'
        year_regex = r'\d{4}'
        left_month = re.search(month_regex, left)
        right_month = re.search(month_regex, right)
        left_year = re.search(year_regex, left)
        right_year = re.search(year_regex, right)

        # If right part is missing month, use left part's month.
        if not right_month and left_month:
            right = left_month.group() + " " + right
        # If right part is missing year, append left part's year.
        if not right_year and left_year:
            right = right + ", " + left_year.group()
        # If left part is missing year but right part has it, append it.
        if not left_year and right_year:
            left = left + ", " + right_year.group()
        return left, right
    else:
        # More than two parts; fallback using first and last parts.
        return parts[0].strip(), parts[-1].strip()

def parse_date_range(date_str):
    """
    Parse a date string that might represent multiple ranges.
    For example, an edge case like:
       "Jun 1 - 2, 2025 and Jun 14 - 18, 2025"
    returns ("Jun 1, 2025", "Jun 18, 2025").
    If there's no 'and', it calls parse_single_range.
    """
    parts = [part.strip() for part in re.split(r'\band\b', date_str, flags=re.IGNORECASE)]
    if len(parts) > 1:
        # Use the first date from the first part and the last date from the last part.
        first_start, _ = parse_single_range(parts[0])
        _, last_end = parse_single_range(parts[-1])
        return first_start, last_end
    else:
        return parse_single_range(date_str)

def generate_ics_content(events, calendar_name):
    """
    Generate ICS (iCalendar) file content from a list of event dictionaries.
    Events should have keys: Subject, Start Date, Start Time, End Date, End Time, All Day Event, Description
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UIU Calendar//Academic Calendar//EN",
        f"X-WR-CALNAME:{calendar_name}",
        "X-WR-TIMEZONE:Asia/Dhaka",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    for event in events:
        # Generate unique ID for this event
        event_uid = str(uuid.uuid4())
        
        # Get current timestamp for DTSTAMP
        now = datetime.now(datetime.now().astimezone().tzinfo).astimezone().strftime("%Y%m%dT%H%M%SZ") if hasattr(datetime, 'UTC') else datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{event_uid}")
        lines.append(f"DTSTAMP:{now}")
        
        # Add summary (event title)
        summary = event.get("Subject", "").replace(',', '\\,').replace(';', '\\;').replace('\n', '\\n')
        lines.append(f"SUMMARY:{summary}")
        
        # Handle dates
        start_date_str = event.get("Start Date", "")
        end_date_str = event.get("End Date", "")
        start_time_str = event.get("Start Time", "")
        end_time_str = event.get("End Time", "")
        is_all_day = event.get("All Day Event", "True") == "True"
        
        try:
            # Parse start date (MM/DD/YYYY format)
            if start_date_str:
                start_date = datetime.strptime(start_date_str, "%m/%d/%Y")
                
                if is_all_day:
                    # All-day events use VALUE=DATE format (YYYYMMDD)
                    lines.append(f"DTSTART;VALUE=DATE:{start_date.strftime('%Y%m%d')}")
                    
                    # For all-day events, end date is exclusive, so add 1 day
                    if end_date_str:
                        end_date = datetime.strptime(end_date_str, "%m/%d/%Y")
                        # Add one day to make it exclusive
                        from datetime import timedelta
                        end_date = end_date + timedelta(days=1)
                        lines.append(f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}")
                    else:
                        # If no end date, use start date + 1 day
                        from datetime import timedelta
                        end_date = start_date + timedelta(days=1)
                        lines.append(f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}")
                else:
                    # Timed events - combine date and time
                    # Note: Since we don't have timezone info in the CSV, we'll use local time
                    if start_time_str:
                        # Parse time and combine with date
                        start_datetime_str = f"{start_date_str} {start_time_str}"
                        # Try multiple time formats
                        for time_fmt in ["%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M"]:
                            try:
                                start_datetime = datetime.strptime(start_datetime_str, time_fmt)
                                lines.append(f"DTSTART:{start_datetime.strftime('%Y%m%dT%H%M%S')}")
                                break
                            except ValueError:
                                continue
                    
                    if end_date_str and end_time_str:
                        end_datetime_str = f"{end_date_str} {end_time_str}"
                        for time_fmt in ["%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M"]:
                            try:
                                end_datetime = datetime.strptime(end_datetime_str, time_fmt)
                                lines.append(f"DTEND:{end_datetime.strftime('%Y%m%dT%H%M%S')}")
                                break
                            except ValueError:
                                continue
        except ValueError as e:
            # If date parsing fails, skip this event's dates
            print(f"Warning: Could not parse date for event '{event.get('Subject', '')}': {e}")
        
        # Add description if available
        description = event.get("Description", "").replace(',', '\\,').replace(';', '\\;').replace('\n', '\\n')
        if description:
            lines.append(f"DESCRIPTION:{description}")
        
        # Add location if available
        location = event.get("Location", "").replace(',', '\\,').replace(';', '\\;').replace('\n', '\\n')
        if location:
            lines.append(f"LOCATION:{location}")
        
        lines.append("END:VEVENT")
    
    lines.append("END:VCALENDAR")
    
    return "\r\n".join(lines)

# Create a folder for CSV files.
csv_folder = "csvs"  # <-- folder name changed to "csvs"
if not os.path.exists(csv_folder):
    os.makedirs(csv_folder)

# URL of the UIU academic calendar page
url = "https://www.uiu.ac.bd/academics/calendar/"

response = requests.get(url)
if response.status_code != 200:
    print("Failed to retrieve page with status code:", response.status_code)
    exit()

soup = BeautifulSoup(response.text, 'html.parser')

# Google Calendar CSV format columns
fields = ["Subject", "Start Date", "Start Time", "End Date", "End Time",
          "All Day Event", "Description", "Location", "Private"]

# Process each dropdown (details block)
for details in soup.find_all("details"):
    summary_tag = details.find("summary")
    if not summary_tag:
        continue
    summary_text = summary_tag.get_text(strip=True)
    # Save CSV files into the csvs folder.
    filename = os.path.join(csv_folder, sanitize_filename(summary_text) + ".csv")

    events = []  # List to hold event rows for this summary

    # Each event is inside a table row <tr> within this details block
    for tr in details.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue  # Skip empty rows

        # Adjust indices according to the actual table structure.
        #   cells[0]: Date (can be a single date, a range, or a complex range)
        #   cells[2]: Event Title (Subject)
        #   cells[3]: Time (expected as "Start Time - End Time")
        raw_date = cells[0] if len(cells) >= 1 else ""
        start_date_str, end_date_str = parse_date_range(raw_date)
        # Format dates to MM/DD/YYYY
        start_date = format_date(start_date_str)
        end_date = format_date(end_date_str)

        event_subject = cells[2] if len(cells) >= 3 else ""

        # Process time field if provided.
        if len(cells) >= 4:
            time_str = cells[3]
            if '-' in time_str:
                times = time_str.split('-')
                start_time = times[0].strip()
                end_time = times[1].strip() if len(times) > 1 else ""
                all_day = "False"
            else:
                start_time = ""
                end_time = ""
                all_day = "True"
        else:
            start_time = ""
            end_time = ""
            all_day = "True"

        # Combine any additional cells into the Description.
        description = " | ".join(cells[4:]) if len(cells) > 4 else ""

        # Construct the event row following the Google Calendar CSV format.
        event_row = {
            "Subject": event_subject,
            "Start Date": start_date,
            "Start Time": start_time,
            "End Date": end_date,
            "End Time": end_time,
            "All Day Event": all_day,
            "Description": description,
            "Location": "",  # Modify if location data is available.
            "Private": "False"
        }

        events.append(event_row)

    # Write out a separate CSV file for this summary if any events were found.
    if events:
        # Write CSV file
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fields)
            writer.writeheader()
            writer.writerows(events)
        print(f"CSV file '{filename}' created with {len(events)} events.")
        
        # Generate and write ICS file
        ics_filename = filename.replace(".csv", ".ics")
        ics_content = generate_ics_content(events, summary_text)
        with open(ics_filename, "w", encoding="utf-8") as icsfile:
            icsfile.write(ics_content)
        print(f"ICS file '{ics_filename}' created with {len(events)} events.")