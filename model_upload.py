#!/usr/bin/env python3
"""
Downloads heart rate data from the server, processes it through the model,
and uploads the results back to the server. Runs continuously until killed.

This script:

1. Downloads heart rate data from the server using the follow API endpoint
   (/api/follow) with polling:
   - Takes an upload_key as input
   - Tracks position to get new records incrementally
   - Uses the X-Follow-Position header to resume from the last position
   - Runs continuously, downloading data in batches

2. Processes the data through the heart rate model:
   - Converts server JSON records to the format expected by model.py
   - Uses chop(), get_heart_rate(), and get_sdnn() from the existing model
   - Generates heart rate predictions and SDNN (standard deviation of NN intervals)

3. Uploads results using a new upload key:
   - Creates a new upload key via /api/new-upload-key (once at startup)
   - Formats predictions as JSON records with timestamp, heart rate, and SDNN
   - Posts to /api/upload in NDJSON format (same as posvel.html)
   - Continues uploading results as new data arrives

Usage:
    nix develop --command python3 model_upload.py <input_upload_key>

Options:
    --min-records: Minimum records to collect before processing (default: 100)
    --no-upload: Process data but don't upload results (for testing)

The script uses Python's standard library (urllib) instead of external dependencies,
and integrates with the Nix development environment that includes scipy, matplotlib,
and numpy.

The script runs continuously until killed with Ctrl+C.
"""

import sys
import time
import json
import argparse
import traceback
from typing import Any, List, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from model import chop, get_heart_rate, get_sdnn

BASE_URL = "https://hr-demo-app-server.vrsa.2kendon.ca"


def parse_csv_line(line: str) -> dict:
    """Parse a CSV line from the server into a dict with the data payload."""
    # Format: index,{json_payload}
    parts = line.split(',', 1)
    if len(parts) != 2:
        raise TypeError("expected a comma")
    return json.loads(parts[1])


def download_data(upload_key: str, min_records: int = 100, start_position: int = 0) -> Tuple[List[dict], int]:
    """
    Download data from the server using the follow API.
    Continues downloading until at least min_records are available.
    Returns the records and the final position.
    """
    position = start_position
    
    url = f"{BASE_URL}/api/follow?upload_key={upload_key}&position={position}"
    
    with urlopen(url, timeout=10) as response:
        status_code = response.status
        
        if status_code == 204:
            return [], position
            
        if status_code != 200:
            raise ValueError(f"status code {status_code}")
        
        # Parse new position from header
        new_position = int(response.headers.get('X-Follow-Position', position))
        
        # Parse lines
        body = response.read().decode('utf-8')
        lines = body.strip().split('\n')
        n_records = 0
        records = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            record = parse_csv_line(line)
            if record:
                records.append(record)
                n_records += 1
        
        print(f"Downloaded {n_records} new records (total: {len(records)}, position: {position} -> {new_position})")
        position = new_position
    return records, position


def convert_records_to_rows(records: List[dict]) -> List[dict]:
    """Convert server records to the format expected by the model."""
    rows = []
    for record in records:
        if 'position' not in record or 'epoch' not in record:
            continue
        
        # Convert epoch (milliseconds) to time struct
        ts = time.gmtime(record['epoch'] / 1000.0)
        
        position = record['position']
        row = {
            'Timestamp': ts,
            'PosX': position.get('x', 0),
            'PosY': position.get('y', 0),
            'PosZ': position.get('z', 0),
        }
        rows.append(row)
    
    return rows


def process_heart_rate(rows: List[dict]) -> Tuple[List[Tuple[Any, float]], float]:
    """Process heart rate data using the model."""
    if len(rows) < 20:
        print(f"Not enough data points ({len(rows)}), need at least 20")
        return [], 0.0
    
    print(f"Processing {len(rows)} data points")
    
    # Convert position to velocity by differentiation
    from model import difference
    rows_with_velocity = list(difference(
        rows,
        keep_original=True,
        keys={'LinVelX': 'PosX', 'LinVelY': 'PosY', 'LinVelZ': 'PosZ'},
    ))
    
    # Chop data into windows
    chopped = list(chop(rows_with_velocity, 5, 20))
    print(f"Created {len(chopped)} windows")
    
    if len(chopped) == 0:
        return [], 0.0
    
    # Calculate heart rate for each window
    predictions = []
    for window in chopped:
        hr = get_heart_rate(window)
        if hr == 0:
            continue
        predictions.append((window[0]['Timestamp'], hr))
    
    print(f"Generated {len(predictions)} heart rate predictions")
    
    # Calculate SDNN
    sdnn = 0.0
    if len(predictions) > 0:
        heart_rates = [hr for _, hr in predictions]
        sdnn = get_sdnn(heart_rates)
        print(f"SDNN: {sdnn * 1000:.3f}ms")
    
    return predictions, sdnn


def create_upload_key() -> Tuple[str, str]:
    """Create a new upload key for results."""
    url = f"{BASE_URL}/api/new-upload-key"
    req = Request(url, method='POST')
    with urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode('utf-8'))
        return data['upload_key'], data['name']


def upload_results(upload_key: str, predictions: List[Tuple[Any, float]], sdnn: float):
    """Upload heart rate predictions to the server."""
    if len(predictions) == 0:
        print("No predictions to upload")
        return
    
    print(f"Uploading {len(predictions)} predictions")
    
    # Create upload records
    lines = []
    for ts, hr in predictions:
        record = {
            'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S", ts),
            'predicted_heart_rate': hr,
            'predicted_sdnn_ms': sdnn * 1000,
            'epoch': int(time.mktime(ts) * 1000)
        }
        lines.append(json.dumps(record))
    
    # Upload in batches
    url = f"{BASE_URL}/api/upload?upload_key={upload_key}"
    body = '\n'.join(lines).encode('utf-8')
    
    req = Request(
        url,
        data=body,
        headers={'Content-Type': 'application/x-ndjson'},
        method='POST'
    )
    
    with urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        print(f"Upload successful: {result['records']} records saved to {result['upload_name']}")


def main():
    parser = argparse.ArgumentParser(
        description='Download heart rate data, process with model, and upload results'
    )
    parser.add_argument(
        'input_upload_key',
        default='0ba7fd59fd0e896f29530f017d20db0a7812be0fd88d9213e75ffb609fac4adfc71861cbb1b2b717c24e23e81c045b71aae9646ec35189de633fdf970a33ba38',
        nargs='?',
        help='Upload key for the input data to download'
    )
    parser.add_argument(
        '--output_upload_key',
        default='4370c5fd80a2707bb7c296d2750f620fd6e2a5d96ab62e20912ab44463af523563e54b168232c5e99293df93dbd24d2134f6a2e6de1eedc9639ee3d78cf6f82b',
        help='Upload key for the output data to upload'
    )
    parser.add_argument(
        '--min-records',
        type=int,
        default=100,
        help='Minimum records to collect before processing (default: 100)'
    )
    parser.add_argument(
        '--no-upload',
        action='store_true',
        help='Process data but do not upload results (for testing)'
    )
    
    args = parser.parse_args()
    
    # Create output upload key once at start if uploading
    output_key = args.output_upload_key
    output_name = None
    if not args.no_upload and args.output_upload_key is None:
        try:
            output_key, output_name = create_upload_key()
            print(f"Created output upload key: {output_name} ({output_key})")
        except Exception as e:
            print(f"Failed to create output upload key: {e}")
            return 1
    
    try:
        print("Starting continuous processing (press Ctrl+C to stop)...")
        
        position = 0  # Track position across all downloads
        
        while True:
            # Download data
            try:
                records, position = download_data(args.input_upload_key, args.min_records, position)
            except Exception as e:
                traceback.print_exc()
                continue
            
            if len(records) == 0:
                continue
            
            # Convert to model format
            rows = convert_records_to_rows(records)
            
            if len(rows) == 0:
                print("No valid data rows, continuing...")
                continue
            
            # Process with model
            predictions, sdnn = process_heart_rate(rows)
            
            if len(predictions) == 0:
                print("No predictions generated, continuing...")
                continue
            
            # Print predictions
            print("\nPredictions:")
            for ts, hr in predictions:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S', ts)}\t{hr:.1f} BPM")
            print(f"\nSDNN: {sdnn * 1000:.3f}ms")
            
            # Upload results
            if not args.no_upload:
                try:
                    upload_results(output_key, predictions, sdnn)
                    print(f"Successfully uploaded results")
                except Exception as e:
                    print(f"Failed to upload results: {e}")
            else:
                print("Skipping upload (--no-upload flag)")
            
            print(f"\nProcessed batch, continuing from position {position}...")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
