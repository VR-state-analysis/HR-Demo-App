from typing import List, Tuple, Any
import os
import sys
import time
import json
from math import sqrt
from scipy.fft import fft, fftfreq
from scipy.signal import find_peaks
import matplotlib.pyplot as plt
import numpy as np

DEBUG = os.getenv('MODEL_DEBUG', False) == 'TRUE'

def peakdet(v, delta: float, x=None):
    """
    Converted from MATLAB script at http://billauer.co.il/peakdet.html

    Returns two arrays

    function [maxtab, mintab]=peakdet(v, delta, x)
    %PEAKDET Detect peaks in a vector
    %        [MAXTAB, MINTAB] = PEAKDET(V, DELTA) finds the local
    %        maxima and minima ("peaks") in the vector V.
    %        MAXTAB and MINTAB consists of two columns. Column 1
    %        contains indices in V, and column 2 the found values.
    %      
    %        With [MAXTAB, MINTAB] = PEAKDET(V, DELTA, X) the indices
    %        in MAXTAB and MINTAB are replaced with the corresponding
    %        X-values.
    %
    %        A point is considered a maximum peak if it has the maximal
    %        value, and was preceded (to the left) by a value lower by
    %        DELTA.

    % Eli Billauer, 3.4.05 (Explicitly not copyrighted).
    % This function is released to the public domain; Any use is allowed.

    """
    maxtab = []
    mintab = []

    if x is None:
        x = np.arange(len(v))

    v = np.asarray(v)

    if len(v) != len(x):
        sys.exit('Input vectors v and x must have same length')

    if not np.isscalar(delta):
        sys.exit('Input argument delta must be a scalar')

    if delta <= 0:
        sys.exit('Input argument delta must be positive')

    mn, mx = np.inf, -np.inf
    mnpos, mxpos = np.nan, np.nan

    lookformax = True

    for i in np.arange(len(v)):
        this = v[i]
        if this > mx:
            mx = this
            mxpos = x[i]
        if this < mn:
            mn = this
            mnpos = x[i]

        if lookformax:
            if this < mx - delta:
                maxtab.append((mxpos, mx))
                mn = this
                mnpos = x[i]
                lookformax = False
        else:
            if this > mn + delta:
                mintab.append((mnpos, mn))
                mx = this
                mxpos = x[i]
                lookformax = True

    return np.array(maxtab), np.array(mintab)


def rows_from_server_dict(d: dict) -> list:
    frames = d['headControllersMotionRecordList']
    time_format = '%Y-%m-%d_%H-%M-%S'
    result = []
    differentiate = False
    for frame in frames:
        # 2024-08-30_15-07-33-6573090
        raw_ts = frame['timeStamp']
        if isinstance(raw_ts, float):
            ts = time.gmtime(raw_ts)
        else:
            ts = time.strptime(frame['timeStamp'][:-8], time_format)
        row = {'Timestamp': ts}
        if 'linVel' in frame:
            row = {**row, **{
                'LinVelX': frame['linVel']['x'],
                'LinVelY': frame['linVel']['y'],
                'LinVelZ': frame['linVel']['z'],
            }}
        else:  # fallback to getting velocity from headPosition
            row = {**row, **{
                'PosX': frame['headPosition']['x'],
                'PosY': frame['headPosition']['y'],
                'PosZ': frame['headPosition']['z'],
            }}
            differentiate = True
        result.append(row)
    if differentiate:
        return list(difference(
            result,
            keep_original=True,
            keys={'LinAccX': 'LinVelX', 'LinAccY': 'LinVelY', 'LinAccZ': 'LinVelZ'},
        ))
    else:
        return result


def parse_row(row, keys={}):
    return {key: parse(row[key]) for key, parse in keys.items()}


def difference(rows, keep_original: bool, keys: dict):
    prev_row = None
    for row in rows:
        if prev_row is not None:
            res = {}
            for new_key, key in keys.items():
                res[new_key] = row[key] - prev_row[key]
            if keep_original:
                res = {**res, **row}
            yield res
        prev_row = row


def get_sampling_freq(rows: list) -> float:
    t1 = time.mktime(rows[0]["Timestamp"])
    t2 = time.mktime(rows[-1]["Timestamp"])
    return 1 / ((t2 - t1) / len(rows))


def mean(rows: list) -> float:
    return sum(rows) / len(rows)


def get_fft(d: list, key):
    sampling_freq = get_sampling_freq(d)
    # print(f'have {len(d)} samples')
    # print(f'sampling freq is {sampling_freq}Hz')
    lin_acc_mean = mean([row[key] for row in d])
    xf = fftfreq(len(d), 1 / sampling_freq)
    yf = fft([row[key] - lin_acc_mean for row in d])
    return xf, yf


def get_peaks2(xf, yf2, left=60 / 60, right=190 / 60):
    maxtab, _ = peakdet(yf2, 0.02)
    # print('maxtab', maxtab)

    for peak_index, peak_value in maxtab:
        peak_index = int(peak_index)
        peak_x = xf[peak_index]
        # print(f'peak_index={peak_index}\tpeak_x={peak_x}\tpeak_value={peak_value}')
        if not (left < peak_x < right):
            continue
        yield peak_x, peak_value


def get_peaks(xf, yf2, left=60 / 60, right=190 / 60):
    peaks, properties = find_peaks(yf2, height=0.2)

    for i, peak in enumerate(peaks):
        if not (left < xf[peak] < right):
            continue
        yield xf[peak], properties['peak_heights'][i]


def chop(rows: list, every: float, length: float):
    t1 = time.mktime(rows[0]["Timestamp"])
    t2 = time.mktime(rows[-1]["Timestamp"])
    duration = t2 - t1
    for i in range(int(duration // every)):
        start = t1 + every * i
        end = start + length
        yield [row for row in rows if start <= time.mktime(row["Timestamp"]) <= end]


def get_heart_rate(rows):
    b = difference(
        rows,
        keep_original=True,
        keys={'LinAccX': 'LinVelX', 'LinAccY': 'LinVelY', 'LinAccZ': 'LinVelZ'},
    )
    c = map(lambda row: {
        **row,
        'LinAcc': sqrt(row['LinAccX'] ** 2 + row['LinAccY'] ** 2 + row['LinAccZ'] ** 2)
    }, b)
    d = list(c)
    xf, yf = get_fft(d, key='LinAcc')
    yf2 = np.abs(yf)
    peakxys = list(get_peaks2(xf, yf2))
    if DEBUG:
        plt.plot(xf, yf2)
        peak_xs = [peakxy[0] for peakxy in peakxys]
        peak_values = [peakxy[1] for peakxy in peakxys]
        print('peak_xs', peak_xs)
        plt.plot(peak_xs, peak_values, 'x', color='b')
        plt.axvline(x=60 / 60, color='r')
        plt.axvline(x=-60 / 60, color='r')
        plt.axvline(x=190 / 60, color='r')
        plt.axvline(x=-190 / 60, color='r')
        ax = plt.gca()
        ax.set_xlim((-5, 5))
        plt.grid()
        plt.show()
    # print(peakxys)
    # TODO: peak selection
    if len(peakxys) == 0:
        return 0
    peakxy_max = max(peakxys, key=lambda peakxy: peakxy[1])
    # print('peakxy_max', peakxy_max)
    # for peakxy in peakxys:
    #    print(f'peak: x={peakxy[0]:03f} Hz, x={peakxy[0]*60:03f} BPM, y={peakxy[1]:03f}')
    # print(f'max peak: x={peakxy_max[0]:03f} Hz, x={peakxy_max[0]*60:03f} BPM, y={peakxy_max[1]:03f}')
    return peakxy_max[0] * 60


def get_nn(heart_rate: float) -> float:
    """
    Returns the NN interval in seconds.
    """
    # NN interval is the time between each beat, so it is equivalent to period
    freq = heart_rate / 60
    period = 1 / freq
    return period


def get_sdnn(heart_rates) -> float:
    """
    Returns the standard deviation of NN intervals in seconds.
    """
    nn_values = list(map(get_nn, filter(lambda hr: hr != 0, heart_rates)))
    return float(np.std(np.array(nn_values)))


def remove_outliers_iqr(values: list):
    q1 = np.percentile(values, 25, method='midpoint')
    q3 = np.percentile(values, 75, method='midpoint')
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return (value for value in values if lower <= value <= upper)


def get_heart_rate_from_server_json_path(path: str) -> Tuple[List[Tuple[Any, float]], float]:
    with open(path, 'r') as file:
        d = json.load(file)
    rows = rows_from_server_dict(d)
    chopped = list(chop(rows, 2, 20))
    predictions = []
    for c in chopped:
        hr = get_heart_rate(c)
        if hr == 0:
            continue
        predictions.append((c[0]['Timestamp'], hr))
    sdnn = get_sdnn(hr for _, hr in predictions)
    return predictions, sdnn


# if __name__ == "__main__":
#     predictions, sdnn = get_heart_rate_from_server_json_path(sys.argv[1])
#     for ts, hr in predictions:
#         print(f'{time.strftime("%Y-%m-%d %H:%M:%S", ts)}\t{hr}')
#     print(f'SDNN: {sdnn * 1000:.3f}ms')
