#!/usr/bin/env python3
"""
CAPTCHA Verification Script

Verifies that a user completed the CAPTCHA by checking if the right controller
touched both panels (top and bottom) for the required duration.
"""

import json
import sys
from typing import Dict, List, Tuple


class CaptchaVerifier:
    def __init__(self, required_duration_ms: int = 2000):
        """
        Initialize the CAPTCHA verifier.
        
        Args:
            required_duration_ms: Required touch duration in milliseconds (default: 2000ms)
        """
        self.required_duration_ms = required_duration_ms
        
        # Panel positions and sizes (matching captcha.html)
        self.top_panel_pos = {'x': 0, 'y': 1.7, 'z': -0.5}
        self.bottom_panel_pos = {'x': 0, 'y': 1.0, 'z': -0.5}
        self.panel_size = {'width': 0.15, 'height': 0.15}
        self.collision_threshold = 0.1  # 10cm threshold
        
    def check_panel_collision(self, controller_pos: Dict[str, float], 
                             panel_pos: Dict[str, float]) -> bool:
        """
        Check if the controller is colliding with a panel.
        
        Args:
            controller_pos: Controller position with x, y, z coordinates
            panel_pos: Panel position with x, y, z coordinates
            
        Returns:
            True if collision detected, False otherwise
        """
        half_width = self.panel_size['width'] / 2
        half_height = self.panel_size['height'] / 2
        
        return (
            abs(controller_pos['x'] - panel_pos['x']) < half_width + self.collision_threshold and
            abs(controller_pos['y'] - panel_pos['y']) < half_height + self.collision_threshold and
            abs(controller_pos['z'] - panel_pos['z']) < self.collision_threshold
        )
    
    def verify_captcha(self, csv_file: str) -> Tuple[bool, Dict]:
        """
        Verify the CAPTCHA from a CSV recording file.
        
        Args:
            csv_file: Path to the CSV file with tracking data
            
        Returns:
            Tuple of (success: bool, details: dict with verification info)
        """
        right_controller_records = []
        
        # Read and parse the CSV file
        with open(csv_file, 'r') as f:
            lines = f.readlines()
            
        # Skip the first line (metadata)
        for line in lines[1:]:
            parts = line.strip().split(',', 1)
            if len(parts) < 2:
                continue
                
            try:
                data = json.loads(parts[1])
                if data.get('trackerKey') == 'rightController':
                    right_controller_records.append(data)
            except json.JSONDecodeError:
                continue
        
        if not right_controller_records:
            return False, {'error': 'No right controller data found'}
        
        # Track panel touch states
        top_panel_touches = []
        bottom_panel_touches = []
        
        current_top_touch = None
        current_bottom_touch = None
        
        # Process each record
        for record in right_controller_records:
            pos = record['position']
            timestamp = record['timestamp']
            
            touching_top = self.check_panel_collision(pos, self.top_panel_pos)
            touching_bottom = self.check_panel_collision(pos, self.bottom_panel_pos)
            
            # Track top panel touches
            if touching_top:
                if current_top_touch is None:
                    current_top_touch = {'start': timestamp, 'end': timestamp}
                else:
                    current_top_touch['end'] = timestamp
            else:
                if current_top_touch is not None:
                    duration = current_top_touch['end'] - current_top_touch['start']
                    top_panel_touches.append({
                        'start': current_top_touch['start'],
                        'end': current_top_touch['end'],
                        'duration_ms': duration
                    })
                    current_top_touch = None
            
            # Track bottom panel touches
            if touching_bottom:
                if current_bottom_touch is None:
                    current_bottom_touch = {'start': timestamp, 'end': timestamp}
                else:
                    current_bottom_touch['end'] = timestamp
            else:
                if current_bottom_touch is not None:
                    duration = current_bottom_touch['end'] - current_bottom_touch['start']
                    bottom_panel_touches.append({
                        'start': current_bottom_touch['start'],
                        'end': current_bottom_touch['end'],
                        'duration_ms': duration
                    })
                    current_bottom_touch = None
        
        # Close any open touches at the end
        if current_top_touch is not None:
            duration = current_top_touch['end'] - current_top_touch['start']
            top_panel_touches.append({
                'start': current_top_touch['start'],
                'end': current_top_touch['end'],
                'duration_ms': duration
            })
        
        if current_bottom_touch is not None:
            duration = current_bottom_touch['end'] - current_bottom_touch['start']
            bottom_panel_touches.append({
                'start': current_bottom_touch['start'],
                'end': current_bottom_touch['end'],
                'duration_ms': duration
            })
        
        # Check if any touch meets the required duration
        top_panel_completed = any(
            touch['duration_ms'] >= self.required_duration_ms 
            for touch in top_panel_touches
        )
        
        bottom_panel_completed = any(
            touch['duration_ms'] >= self.required_duration_ms 
            for touch in bottom_panel_touches
        )
        
        captcha_success = top_panel_completed and bottom_panel_completed
        
        # Find longest touches
        longest_top = max(top_panel_touches, key=lambda t: t['duration_ms']) if top_panel_touches else None
        longest_bottom = max(bottom_panel_touches, key=lambda t: t['duration_ms']) if bottom_panel_touches else None
        
        details = {
            'captcha_passed': captcha_success,
            'required_duration_ms': self.required_duration_ms,
            'top_panel': {
                'completed': top_panel_completed,
                'touch_count': len(top_panel_touches),
                'longest_touch_ms': longest_top['duration_ms'] if longest_top else 0,
                'all_touches': top_panel_touches
            },
            'bottom_panel': {
                'completed': bottom_panel_completed,
                'touch_count': len(bottom_panel_touches),
                'longest_touch_ms': longest_bottom['duration_ms'] if longest_bottom else 0,
                'all_touches': bottom_panel_touches
            }
        }
        
        return captcha_success, details


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_captcha.py <captcha_recording.csv>")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    
    verifier = CaptchaVerifier(required_duration_ms=2000)
    success, details = verifier.verify_captcha(csv_file)
    
    print("=" * 60)
    print("CAPTCHA VERIFICATION REPORT")
    print("=" * 60)
    print(f"\nFile: {csv_file}")
    print(f"Required Duration: {details['required_duration_ms']}ms ({details['required_duration_ms']/1000:.1f}s)")
    print("\n" + "-" * 60)
    print("TOP PANEL")
    print("-" * 60)
    print(f"Status: {'✓ COMPLETED' if details['top_panel']['completed'] else '✗ FAILED'}")
    print(f"Touch Count: {details['top_panel']['touch_count']}")
    print(f"Longest Touch: {details['top_panel']['longest_touch_ms']:.0f}ms ({details['top_panel']['longest_touch_ms']/1000:.2f}s)")
    
    if details['top_panel']['all_touches']:
        print("\nAll touches:")
        for i, touch in enumerate(details['top_panel']['all_touches'], 1):
            status = "✓" if touch['duration_ms'] >= details['required_duration_ms'] else "✗"
            print(f"  {status} Touch {i}: {touch['duration_ms']:.0f}ms ({touch['start']:.0f}ms - {touch['end']:.0f}ms)")
    
    print("\n" + "-" * 60)
    print("BOTTOM PANEL")
    print("-" * 60)
    print(f"Status: {'✓ COMPLETED' if details['bottom_panel']['completed'] else '✗ FAILED'}")
    print(f"Touch Count: {details['bottom_panel']['touch_count']}")
    print(f"Longest Touch: {details['bottom_panel']['longest_touch_ms']:.0f}ms ({details['bottom_panel']['longest_touch_ms']/1000:.2f}s)")
    
    if details['bottom_panel']['all_touches']:
        print("\nAll touches:")
        for i, touch in enumerate(details['bottom_panel']['all_touches'], 1):
            status = "✓" if touch['duration_ms'] >= details['required_duration_ms'] else "✗"
            print(f"  {status} Touch {i}: {touch['duration_ms']:.0f}ms ({touch['start']:.0f}ms - {touch['end']:.0f}ms)")
    
    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)
    
    if success:
        print("✓ CAPTCHA PASSED - Both panels touched for required duration")
        sys.exit(0)
    else:
        print("✗ CAPTCHA FAILED - Requirements not met")
        sys.exit(1)


if __name__ == "__main__":
    main()
