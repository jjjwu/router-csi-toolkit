#!/usr/bin/env python3
"""Analyze a csi_capture.py raw CSI recording.

The capture file is a sequence of records:
    <float64 host timestamp> <uint16 payload length> <payload>

Payload layout matches mt76-csi-daemon/src/udp.c:
    24-byte header + data_num interleaved int16 I/Q pairs.

This tool selects the record whose chain_info bit 15 is set for each
measurement (one measurement usually contains 4 or 8 chain records),
extracts the 256-subcarrier amplitude matrix, and writes:
    csi_amplitude_heatmap.png
    csi_mean_amplitude_motion.png
    csi_analysis_summary.txt
"""

import argparse
import copy
import os
import struct
import sys
import warnings
from collections import Counter

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


HDR = struct.Struct("<I6sbBBBBBHHHH")
REC = struct.Struct("<dH")


def iter_records(path):
    with open(path, "rb") as f:
        while True:
            raw = f.read(REC.size)
            if len(raw) < REC.size:
                break
            timestamp, length = REC.unpack(raw)
            payload = f.read(length)
            if len(payload) < HDR.size:
                continue
            yield timestamp, payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", help="raw capture produced by csi_capture.py")
    parser.add_argument("--outdir", default="logs/analysis")
    parser.add_argument("--subcarriers", type=int, default=256)
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    records = 0
    measurements = 0
    skipped_small = 0
    skipped_null = 0
    skipped_anomalous = 0
    data_num_counter = Counter()
    bw_counter = Counter()
    station_counter = Counter()
    times = []
    amplitudes = []
    median_amplitudes = []
    rssis = []
    snrs = []

    pending = []
    for timestamp, payload in iter_records(args.capture):
        records += 1
        ts, ta, rssi, snr, bw, ch, mode, pad, num, tx, rx, chain = HDR.unpack_from(payload)
        data_num_counter[num] += 1
        bw_counter[bw] += 1
        station_counter[ta.hex(":")] += 1

        if not (chain & 0x8000):
            pending.append((payload, num))
            continue
        measurements += 1
        group = pending + [(payload, num)]
        pending = []

        # Only some chain records of a measurement carry real I/Q data; on
        # GL-MT6000 the record flagged by chain_info bit 15 is always zero.
        # Prefer tx0/rx0 when valid, otherwise take the strongest valid one.
        chosen = None
        strongest = None
        for item, item_num in group:
            if item_num != args.subcarriers:
                continue
            iq = np.frombuffer(
                item[HDR.size:HDR.size + item_num * 4], dtype="<i2"
            )
            if iq.size < item_num * 2 or not iq.any():
                continue
            i = iq[0::2].astype(np.float64)
            q = iq[1::2].astype(np.float64)
            amp_db = 20.0 * np.log10(np.sqrt(i * i + q * q) + 1e-9)
            if float(amp_db.mean()) < 0.0:
                continue
            value = float(amp_db.mean())
            if strongest is None or value > strongest[0]:
                strongest = (value, amp_db, item)
            item_tx, item_rx = struct.unpack_from("<HH", item, 18)
            if (item_tx, item_rx) == (0, 0):
                chosen = (amp_db, item)

        if chosen is None:
            if strongest is None:
                skipped_null += 1
                continue
            chosen = (strongest[1], strongest[2])
        amp_db, chosen_item = chosen
        _ts, _ta, rssi, snr = HDR.unpack_from(chosen_item, 0)[0:4]

        zero_fraction = float(np.mean(amp_db < -50.0))
        if zero_fraction > 0.5:
            skipped_anomalous += 1
            continue

        times.append(timestamp)
        amplitudes.append(amp_db)
        median_amplitudes.append(float(np.median(amp_db)))
        rssis.append(rssi)
        snrs.append(snr)

    if not amplitudes:
        sys.exit("no usable CSI measurements found")

    t = np.asarray(times, dtype=np.float64)
    t = t - t[0]
    matrix = np.vstack(amplitudes)
    representative_amp = np.asarray(median_amplitudes, dtype=np.float64)
    valid_amp = matrix[matrix > -100.0]

    duration = float(t[-1] - t[0])
    measurement_rate = len(t) / max(duration, 1e-9)
    gaps = np.diff(t)

    summary_lines = [
        f"capture={args.capture}",
        f"records={records}",
        f"measurements={measurements}",
        f"skipped_null={skipped_null}",
        f"measurements_used={len(t)}",
        f"skipped_non_{args.subcarriers}sc={skipped_small}",
        f"skipped_anomalous={skipped_anomalous}",
        f"duration_s={duration:.3f}",
        f"measurement_rate_hz={measurement_rate:.3f}",
        f"data_num={dict(data_num_counter)}",
        f"bandwidth_code={dict(bw_counter)}",
        f"stations={dict(station_counter)}",
        f"rssi_min_avg_max={min(rssis)}/{np.mean(rssis):.2f}/{max(rssis)}",
        f"snr_min_avg_max={min(snrs)}/{np.mean(snrs):.2f}/{max(snrs)}",
        f"amplitude_db_min={valid_amp.min():.3f}",
        f"amplitude_db_max={valid_amp.max():.3f}",
        f"amplitude_db_mean={valid_amp.mean():.3f}",
        f"per_subcarrier_std_mean={matrix.std(axis=0).mean():.3f}",
        f"median_amplitude_db_std={representative_amp.std():.3f}",
        f"gap_s_p50={np.percentile(gaps, 50):.6f}" if gaps.size else "gap_s_p50=nan",
        f"gap_s_p95={np.percentile(gaps, 95):.6f}" if gaps.size else "gap_s_p95=nan",
        f"gap_s_max={gaps.max():.6f}" if gaps.size else "gap_s_max=nan",
        f"gaps_gt_1s={int((gaps > 1.0).sum())}" if gaps.size else "gaps_gt_1s=0",
        f"gaps_gt_5s={int((gaps > 5.0).sum())}" if gaps.size else "gaps_gt_5s=0",
    ]

    # Mask the DC/null subcarriers around the center for visualization.
    heat = matrix.copy()
    center = heat.shape[1] // 2
    for idx in range(max(0, center - 2), min(heat.shape[1], center + 2)):
        heat[:, idx] = np.nan

    # Normalized subcarrier-vs-time heatmap: remove each subcarrier's median
    # and clip to +/-10 dB so temporal changes are visible.
    cmap = copy.copy(plt.get_cmap("coolwarm"))
    cmap.set_bad("black")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        normalized = heat - np.nanmedian(heat, axis=0, keepdims=True)
    normalized = np.clip(normalized, -10.0, 10.0)
    plt.figure(figsize=(13, 6))
    plt.imshow(
        normalized.T,
        aspect="auto",
        origin="lower",
        extent=[t[0], t[-1], 0, normalized.shape[1]],
        cmap=cmap,
        vmin=-10.0,
        vmax=10.0,
    )
    plt.colorbar(label="Relative amplitude (dB)")
    plt.xlabel("Time (s)")
    plt.ylabel("Subcarrier index")
    plt.title("GL-MT6000 MT7986 CSI normalized amplitude, 256 subcarriers")
    plt.tight_layout()
    plt.savefig(os.path.join(args.outdir, "csi_amplitude_heatmap.png"), dpi=150)
    plt.close()

    # Raw amplitude heatmap with percentile clipping.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        vmin, vmax = np.nanpercentile(heat, [5, 95])
    plt.figure(figsize=(13, 6))
    plt.imshow(
        heat.T,
        aspect="auto",
        origin="lower",
        extent=[t[0], t[-1], 0, heat.shape[1]],
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
    )
    plt.colorbar(label="Amplitude (dB)")
    plt.xlabel("Time (s)")
    plt.ylabel("Subcarrier index")
    plt.title("GL-MT6000 MT7986 CSI raw amplitude, 256 subcarriers (5-95% color scale)")
    plt.tight_layout()
    plt.savefig(os.path.join(args.outdir, "csi_amplitude_heatmap_raw.png"), dpi=150)
    plt.close()

    # Mean amplitude and a simple 1-second rolling motion indicator.
    grid = np.linspace(t[0], t[-1], max(2, int(duration * 20) + 1))
    resampled = np.interp(grid, t, representative_amp)
    window = max(1, int(1.0 * (grid.size - 1) / max(grid[-1] - grid[0], 1e-9)))
    kernel = np.ones(window) / window
    smooth = np.convolve(resampled, kernel, mode="same")
    motion = np.sqrt(np.maximum(np.convolve((resampled - smooth) ** 2, kernel, mode="same"), 0.0))

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    axes[0].plot(t, representative_amp, linewidth=0.8, label="median amplitude")
    axes[0].set_ylabel("Median amplitude (dB)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="upper right")
    axes[1].plot(grid, motion, color="tab:orange", linewidth=0.9)
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Rolling std (dB)")
    axes[1].grid(True, alpha=0.3)
    plt.suptitle("GL-MT6000 CSI mean amplitude and 1-second rolling variation")
    plt.tight_layout()
    plt.savefig(os.path.join(args.outdir, "csi_mean_amplitude_motion.png"), dpi=150)
    plt.close()

    summary_lines.extend(
        [
            f"motion_indicator_mean_db={motion.mean():.3f}",
            f"motion_indicator_max_db={motion.max():.3f}",
            f"heatmap={os.path.join(args.outdir, 'csi_amplitude_heatmap.png')}",
            f"heatmap_raw={os.path.join(args.outdir, 'csi_amplitude_heatmap_raw.png')}",
            f"motion_plot={os.path.join(args.outdir, 'csi_mean_amplitude_motion.png')}",
        ]
    )

    summary = "\n".join(summary_lines) + "\n"
    with open(os.path.join(args.outdir, "csi_analysis_summary.txt"), "w") as f:
        f.write(summary)
    print(summary, end="")


if __name__ == "__main__":
    main()

