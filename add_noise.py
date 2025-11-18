#!/usr/bin/env python3
"""
Add Gaussian Noise to CAPTCHA CSV File

Adds configurable Gaussian noise to position and rotation data in tracking CSV files.
This can be used to test robustness of verification or simulate sensor inaccuracies.
"""

import json
import sys
import argparse
import numpy as np
from typing import Dict, Optional


class NoiseAdder:
    def __init__(self, position_std: float = 0.01, rotation_std: float = 0.01):
        """
        Initialize the noise adder.
        
        Args:
            position_std: Standard deviation for position noise in meters (default: 0.01m = 1cm)
            rotation_std: Standard deviation for rotation quaternion noise (default: 0.01)
        """
        self.position_std = position_std
        self.rotation_std = rotation_std
        
    def add_noise_to_position(self, position: Dict[str, float]) -> Dict[str, float]:
        """
        Add Gaussian noise to a position vector.
        
        Args:
            position: Dictionary with x, y, z coordinates
            
        Returns:
            Dictionary with noisy x, y, z coordinates
        """
        return {
            'x': position['x'] + np.random.normal(0, self.position_std),
            'y': position['y'] + np.random.normal(0, self.position_std),
            'z': position['z'] + np.random.normal(0, self.position_std)
        }
    
    def add_noise_to_rotation(self, rotation: Dict) -> Dict:
        """
        Add Gaussian noise to a quaternion rotation.
        
        Args:
            rotation: Dictionary with quaternion components (_x, _y, _z, _w or x, y, z, w)
            
        Returns:
            Dictionary with noisy quaternion (normalized)
        """
        # Handle both _x/_y/_z/_w and x/y/z/w formats
        if '_x' in rotation:
            quat = np.array([
                rotation['_x'],
                rotation['_y'],
                rotation['_z'],
                rotation['_w']
            ])
            key_prefix = '_'
        else:
            quat = np.array([
                rotation['x'],
                rotation['y'],
                rotation['z'],
                rotation['w']
            ])
            key_prefix = ''
        
        # Add noise to quaternion components
        noisy_quat = quat + np.random.normal(0, self.rotation_std, size=4)
        
        # Normalize the quaternion to maintain unit length
        noisy_quat = noisy_quat / np.linalg.norm(noisy_quat)
        
        # Return in the same format as input
        result = {
            f'{key_prefix}x': float(noisy_quat[0]),
            f'{key_prefix}y': float(noisy_quat[1]),
            f'{key_prefix}z': float(noisy_quat[2]),
            f'{key_prefix}w': float(noisy_quat[3])
        }
        
        if 'isQuaternion' in rotation:
            result['isQuaternion'] = rotation['isQuaternion']
            
        return result
    
    def process_csv(self, input_file: str, output_file: str, 
                   seed: Optional[int] = None) -> Dict:
        """
        Process a CSV file and add noise to all tracking data.
        
        Args:
            input_file: Path to input CSV file
            output_file: Path to output CSV file
            seed: Optional random seed for reproducibility
            
        Returns:
            Dictionary with processing statistics
        """
        if seed is not None:
            np.random.seed(seed)
        
        processed_count = 0
        
        with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
            lines = f_in.readlines()
            
            # Write the first line (metadata) unchanged
            if lines:
                f_out.write(lines[0])
            
            # Process remaining lines
            for line in lines[1:]:
                parts = line.strip().split(',', 1)
                if len(parts) < 2:
                    f_out.write(line)
                    continue
                
                line_num = parts[0]
                
                try:
                    data = json.loads(parts[1])
                    
                    # Add noise to position if present
                    if 'position' in data:
                        data['position'] = self.add_noise_to_position(data['position'])
                    
                    # Add noise to rotation if present
                    if 'rotation' in data:
                        data['rotation'] = self.add_noise_to_rotation(data['rotation'])
                    
                    # Write modified line
                    f_out.write(f"{line_num},{json.dumps(data)}\n")
                    processed_count += 1
                    
                except json.JSONDecodeError:
                    # Write line unchanged if parsing fails
                    f_out.write(line)
        
        stats = {
            'input_file': input_file,
            'output_file': output_file,
            'processed_records': processed_count,
            'position_noise_std_m': self.position_std,
            'rotation_noise_std': self.rotation_std,
            'seed': seed
        }
        
        return stats


def main():
    parser = argparse.ArgumentParser(
        description='Add Gaussian noise to CAPTCHA tracking CSV files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s captcha-example.csv noisy.csv
  %(prog)s captcha-example.csv noisy.csv --position-std 0.02
  %(prog)s captcha-example.csv noisy.csv --position-std 0.01 --rotation-std 0.01 --seed 42
        '''
    )
    
    parser.add_argument('input', metavar='INPUT',
                        help='Input CSV file with tracking data')
    parser.add_argument('output', metavar='OUTPUT',
                        help='Output CSV file with noisy data')
    parser.add_argument('--position-std', type=float, default=0.01,
                        metavar='M',
                        help='Position noise std dev in meters (default: 0.01 = 1cm)')
    parser.add_argument('--rotation-std', type=float, default=0.01,
                        metavar='R',
                        help='Rotation quaternion noise std dev (default: 0.01)')
    parser.add_argument('--seed', type=int, default=None,
                        metavar='S',
                        help='Random seed for reproducibility (optional)')
    
    args = parser.parse_args()
    
    adder = NoiseAdder(position_std=args.position_std, rotation_std=args.rotation_std)
    stats = adder.process_csv(args.input, args.output, seed=args.seed)
    
    print("=" * 60)
    print("NOISE ADDITION REPORT")
    print("=" * 60)
    print(f"\nInput File:  {stats['input_file']}")
    print(f"Output File: {stats['output_file']}")
    print(f"\nProcessed Records: {stats['processed_records']}")
    print(f"\nNoise Parameters:")
    print(f"  Position Std Dev: {stats['position_noise_std_m']:.4f}m ({stats['position_noise_std_m']*100:.2f}cm)")
    print(f"  Rotation Std Dev: {stats['rotation_noise_std']:.4f}")
    if stats['seed'] is not None:
        print(f"  Random Seed: {stats['seed']}")
    else:
        print(f"  Random Seed: None (non-reproducible)")
    
    print("\n" + "=" * 60)
    print("✓ Noise added successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
