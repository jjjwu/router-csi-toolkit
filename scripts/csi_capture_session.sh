#!/bin/sh
# Start a timestamped CSI capture session on the Mac.
#
# Usage:
#   scripts/csi_capture_session.sh [seconds] [udp_port] [output_dir]
#
# Examples:
#   scripts/csi_capture_session.sh 600
#   scripts/csi_capture_session.sh 3600 8888 logs

set -eu

SECONDS_TO_CAPTURE="${1:-600}"
UDP_PORT="${2:-8888}"
OUTDIR="${3:-logs}"

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CAPTURE_TOOL="$PROJECT_ROOT/scripts/csi_capture.py"

mkdir -p "$OUTDIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTFILE="$OUTDIR/csi_capture_$TIMESTAMP.bin"
LOGFILE="$OUTDIR/csi_capture_$TIMESTAMP.txt"

echo "capture: ${SECONDS_TO_CAPTURE}s, UDP port ${UDP_PORT}"
echo "raw:     $OUTFILE"
echo "log:     $LOGFILE"

python3 "$CAPTURE_TOOL" "$OUTFILE" --port "$UDP_PORT" --seconds "$SECONDS_TO_CAPTURE" 2>&1 |
	tee "$LOGFILE"

echo "analysis:"
python3 "$PROJECT_ROOT/scripts/analyze_csi_capture.py" "$OUTFILE" --outdir "$OUTDIR/analysis_$TIMESTAMP"

