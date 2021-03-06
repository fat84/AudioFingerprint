from Database import DbHelper
import hashlib
from numba import jit
import numpy as np

db = DbHelper()

# Frequency ranges for sequential hashing
FREQUENY_RANGES = (500,  1000, 1500, 2000, 2500, 3000, 3500, 4000, 10000000)
TOT_RANGES = len(FREQUENY_RANGES)

# Length of hash string
HASHLEN = 25

@jit(nopython=True)
def get_range_idx(freq):
    i = 0
    while FREQUENY_RANGES[i] < freq:
        i += 1
    return i

def hash_sequential(peaks, spectrum, t, freq):
    """
    Take 4 sequential points within multiple
    ranges 0-500, 500-1000, ... , 3500-4000

    Put together the frequencies and time differences of these points
    to produce a hash
    """
    freq = freq[peaks[0]]
    times = t[peaks[1]]
    # Sort peaks by time
    sort_order = np.argsort(times)
    peak_times = times[sort_order]
    peak_freq = freq[sort_order]
    # Rounding
    peak_freq = np.around(peak_freq, -1)  # Round frequencies to nearest 10
    peak_times = np.around(peak_times * 1000, -1)  # Round times to nearest 10 ms

    freq_buffer = [[0]] * TOT_RANGES
    time_buffer = [[0]] * TOT_RANGES

    MIN_TIME_DELTA = 0

    for i in range(len(peak_freq)):
        freq = peak_freq[i]
        time = peak_times[i]

        range_idx = get_range_idx(freq)

        if range_idx < TOT_RANGES - 2:  # Frequency must be in range
            #if(time - time_buffer[range_idx][-1]) >= MIN_TIME_DELTA:  # Minimum time between
            freq_buffer[range_idx].append(freq)
            time_buffer[range_idx].append(time)
            if len(freq_buffer[range_idx]) > 4:
                yield freq_buffer[range_idx][-4:], time_buffer[range_idx][-4:]


def get_hashstr_sequential(freqs, times):
    """
    Calculates hash with four consecutive frequencies
    """
    tp = (str(freqs[0]), str(freqs[1]), str(freqs[2]), str(freqs[3]))
    hash_ob = hashlib.sha1(str("%s %s %s %s" % tp).encode('utf-8'))

    return hash_ob.digest()[:HASHLEN], times[0]


"""
Finds highest peaks in each time segment.
Hashes the frequencies of two consecutive peaks and the time difference between them
"""
TOP_FREQ = 5000
WINDOW = 100  # Max peak in 100ms window
def hash_window(spectrum, t, freq):
    max_time = t[-1]

    time_win_idxs = [0]
    last_div = 0

    for i in range(len(t)):
        cur_win_count = t[i] // WINDOW
        if cur_win_count > last_div:
            time_win_idxs.append(i)
            last_div = cur_win_count

    idx = 0
    for idx in range(len(freq)):  # Find maximum allowed frequency index
        if freq[idx] > TOP_FREQ: break
    max_freq_idx = idx

    last_max_freq = None  # Indexes of last biggest amplitude in window
    last_max_time = None

    for i in range(len(time_win_idxs)-1):
        time_range = spectrum[time_win_idxs[i]:time_win_idxs[i+1]][:max_freq_idx]
        max_idx = np.unravel_index(time_range.argmax(), time_range.shape)  # Relative index of peak

        max_idx = (max_idx[0] + time_win_idxs[i], max_idx[1])  # Absolute index in transposed spectrum

        if last_max_freq is not None:
            yield t[last_max_time], t[max_idx[0]], freq[last_max_freq], freq[max_idx[1]]

        last_max_time, last_max_freq = max_idx[0], max_idx[1]


def get_hashstr_window(time1, time2, freq1, freq2):
    """
    Calculates hash for each node and the following window
    """
    time_dif = time2 - time1
    tp = (str(freq1), str(freq2), str(time_dif))
    hash_ob = hashlib.sha1(str("%s %s %s" % tp).encode('utf-8'))

    return hash_ob.digest()[:HASHLEN], time1


FAN_OUT = 10        # Each peak will be hashed together with at most 10 other peaks
ZONE_DELAY = 100    # Start of target zone 10ms after peak
ZONE_LEN = 1000     # Length of the zone in ms
ZONE_HEIGHT = 1000  # Height of the zone in hertz

@jit
def hash_anchor(peaks, spectrum, t, freq):
    """
    Find highest peak in a time and frequency-window
    Pair found peak with top 10 highest peaks which occur up to 100ms after the peak
    and whose frequency is between f-500 and f+500 Hz

    For each such pair hash their frequencies and the time difference between them
    """
    zh2 = ZONE_HEIGHT//2
    zl2 = ZONE_LEN//2

    freq = freq[peaks[0]]
    times = t[peaks[1]]

    # Sort peaks by time
    sort_order = np.argsort(times)
    peak_times = times[sort_order]
    peak_freq = freq[sort_order]

    # Rounding
    peak_freq = np.around(peak_freq, -1)  # Round frequencies to nearest 10
    peak_times = np.around(peak_times * 1000, -1)  # Round times to nearest 10 ms

    open_peaks = []
    pair_counts = []
    start_idx = 0  # Index for starting the search

    results = []

    for i in range(len(peak_times)):
        cur_time = peak_times[i]  # Peaks are sorted by time
        cur_freq = peak_freq[i]
        peak = (cur_time, cur_freq)
        for j in range(start_idx, len(open_peaks)):
            anchor_time, anchor_freq = open_peaks[j]
            if anchor_time + ZONE_DELAY + ZONE_LEN > cur_time:         # Current peak in zone
                if anchor_time + ZONE_DELAY < cur_time:                # If peak is delayed enough
                    if cur_freq - zh2 < anchor_freq < cur_freq + zh2:  # If frequency in range
                        if pair_counts[j] < FAN_OUT:                   # If fan_out limit hasn't been reached
                            pair_counts[j] += 1
                            results.append((get_hashstr_anchor(anchor_time, cur_time, anchor_freq, cur_freq), anchor_time))
            else:
                # Start next time from a node which could be in time zone
                start_idx = j

        open_peaks.append(peak)  # Add new peak to open list
        pair_counts.append(0)

        if len(results) + 1 % 1001 == 0:
            print(len(results))

    return results

import ctypes
def get_hashstr_anchor(time1, time2, freq1, freq2):
    """
    Calculates hash for each node and the following window
    Returns unsigned integer of the hash
    """
    time_dif = time2 - time1
    tp = (str(freq1), str(freq2), str(time_dif))
    hash_ob = hashlib.sha1(str("%s %s %s" % tp).encode('utf-8'))

    int_val = int.from_bytes(hash_ob.digest(), 'big')
    return ctypes.c_uint32(int_val)