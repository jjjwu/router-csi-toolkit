#!/bin/sh
# Capture the CSI UDP stream on a Linux analysis host.
#
# The GL-MT6000 daemon sends one datagram per chain record to
# <host>:<port> (see /etc/mt76-csi.conf). This script records them with
# the project's csi_capture.py and then runs the amplitude/motion
# analysis when numpy + matplotlib are available.
#
# Usage:
#   scripts/csi_capture_linux.sh [seconds] [udp_port] [output_dir]
#
# Examples:
#   scripts/csi_capture_linux.sh 600
#   scripts/csi_capture_linux.sh 3600 8888 ~/csi-captures
#
# Analysis deps (Ubuntu):
#   sudo apt install -y python3-numpy python3-matplotlib
# or run the analysis in a container:
#   docker run --rm -v "$PWD":/w -w /w python:3.11-slim \
#       sh -c 'pip install numpy matplotlib && python scripts/analyze_csi_capture.py <file> --outdir <dir>'

set -eu

SECONDS_TO_CAPTURE="${1:-600}"
UDP_PORT="${2:-8888}"
OUTDIR="${3:-$HOME/csi-captures}"

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CAPTURE_TOOL="$PROJECT_ROOT/scripts/csi_capture.py"
ANALYZE_TOOL="$PROJECT_ROOT/scripts/analyze_csi_capture.py"

if [ ! -f "$CAPTURE_TOOL" ]; then
	echo "csi_capture.py not found at $CAPTURE_TOOL" >&2
	exit 1
fi

mkdir -p "$OUTDIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTFILE="$OUTDIR/csi_capture_$TIMESTAMP.bin"
ANALYSIS_DIR="$OUTDIR/analysis_$TIMESTAMP"

echo "capture: ${SECONDS_TO_CAPTURE}s on UDP ${UDP_PORT}"
echo "raw:     $OUTFILE"

python3 "$CAPTURE_TOOL" "$OUTFILE" --port "$UDP_PORT" --seconds "$SECONDS_TO_CAPTURE"

if [ ! -f "$ANALYZE_TOOL" ]; then
	echo "analyze_csi_capture.py not found; raw capture kept at $OUTFILE"
	exit 0
fi

if python3 -c 'import numpy, matplotlib' 2>/dev/null; then
	echo "analysis -> $ANALYSIS_DIR"
	python3 "$ANALYZE_TOOL" "$OUTFILE" --outdir "$ANALYSIS_DIR"
else
	echo
	echo "numpy/matplotlib missing; install them and re-run:"
	echo "  sudo apt install -y python3-numpy python3-matplotlib"
	echo "  python3 $ANALYZE_TOOL $OUTFILE --outdir $ANALYSIS_DIR"
	echo
	echo "or in Docker:"
	echo "  docker run --rm -v $PROJECT_ROOT:/w -w /w python:3.11-slim \\"
	echo "    sh -c 'pip install numpy matplotlib && python scripts/analyze_csi_capture.py $OUTFILE --outdir $ANALYSIS_DIR'"
fi
