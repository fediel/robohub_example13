#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

export ADSP_LIBRARY_PATH="$SCRIPT_DIR/resources/qnn236/"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$SCRIPT_DIR/resources/qnn236/"

echo "🚀 Starting System from: $SCRIPT_DIR"
echo "🔧 Libraries: $ADSP_LIBRARY_PATH"

python3 python/run.py "$@"