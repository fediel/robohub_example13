#!/bin/bash

PROJECT_ROOT=$(cd "$(dirname "$0")"; pwd)
TARGET_LIB_DIR="$PROJECT_ROOT/resources/qnn236"

echo "-------------------------------------------------------"
echo "QNN Dependency Extractor for segmentanything"
echo "-------------------------------------------------------"

function show_help() {
    echo "Error: QNN_SDK_ROOT is not set or invalid."
    echo ""
    echo "To use this project, you need the Qualcomm QNN SDK:"
    echo "1. Download Qualcomm QNN SDK v2.36.0.250627. "
    echo "2. Unzip the SDK to your local machine."
    echo "3. Run this script with the path to the SDK:"
    echo "   usage: sh $0 /path/to/qualcomm_qnn_sdk_root"
    echo ""
    exit 1
}

if [ -z "$1" ]; then
    show_help
fi

QNN_SDK_ROOT=$1

if [ ! -f "$QNN_SDK_ROOT/include/QNN/QnnCommon.h" ]; then
    echo "Error: The provided path does not look like a valid QNN SDK root."
    show_help
fi

echo "SDK Found at: $QNN_SDK_ROOT"
echo "Extracting dependencies to $TARGET_LIB_DIR..."

mkdir -p "$TARGET_LIB_DIR"

LIBS_TO_COPY=(
    "lib/aarch64-oe-linux-gcc11.2/libQnnHtp.so"
    "lib/aarch64-oe-linux-gcc11.2/libQnnHtpNetRunExtensions.so"
    "lib/aarch64-oe-linux-gcc11.2/libQnnHtpPrepare.so"
    "lib/aarch64-oe-linux-gcc11.2/libQnnSystem.so"
    "lib/aarch64-oe-linux-gcc11.2/libQnnHtpV73Stub.so"
    "lib/hexagon-v73/unsigned/libQnnHtpV73Skel.so"
)

for lib in "${LIBS_TO_COPY[@]}"; do
    SRC_PATH="$QNN_SDK_ROOT/$lib"
    if [ -f "$SRC_PATH" ]; then
        cp "$SRC_PATH" "$TARGET_LIB_DIR/"
        echo "Successfully copied: $(basename "$lib")"
    else
        echo "Warning: Could not find $lib, skipping..."
    fi
done

echo "-------------------------------------------------------"
echo "Setup Complete! Dependencies are now in $TARGET_LIB_DIR"
echo "-------------------------------------------------------"