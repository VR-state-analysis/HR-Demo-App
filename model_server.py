import time
import csv
import sys
import functools

from dateutil.parser import parse as dateutil_parse

from model import chop, get_heart_rate, get_sdnn, parse_row


parse_timestamp = lambda s: time.strptime(s[:-1], "%Y-%m-%d_%H-%M-%S-%f")

format_iso8601 = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%S", ts)
format_unix = lambda ts: time.mktime(ts)

KEYS = {
    "Timestamp": parse_timestamp,
    # example Timestamp: 2024-09-06_17-37-17-0347440
    # NOTE: use "dateutil_parse" for ISO 8601 / RFC 3339 timestamps
    "LinVelX": float,
    "LinVelY": float,
    "LinVelZ": float,
}


input_data_path = sys.argv[1]

with open(input_data_path, 'r') as file:
    rows = csv.DictReader(file)
    a = list(map(functools.partial(parse_row, keys=KEYS), rows))
    chopped = list(chop(a, 5, 20))
    predictions = list(map(get_heart_rate, chopped))
    sdnn = get_sdnn(predictions)

writer = csv.writer(sys.stdout)
writer.writerow(['timestamp', 'predicted_heart_rate', 'predicted_sdnn_ms'])
for i, p in enumerate(predictions):
    chop = chopped[i]
    start_ts = chop[0]['Timestamp']
    # NOTE: switch format_iso8601 to format_unix to change to Unix epoch, etc
    writer.writerow([format_iso8601(start_ts), p, sdnn*1000])
