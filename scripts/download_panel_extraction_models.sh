#!/bin/bash
# Download YOLOv5 panel extraction model weights
# Usage: scripts/download_panel_extraction_models.sh

set -e

MODEL_DIR="models/panel_extraction"
mkdir -p "$MODEL_DIR"

echo "Downloading YOLOv5 panel extraction models..."
echo "This will download ~50MB of model weights from Google Drive."

# Check if gdown is installed
if ! command -v gdown &> /dev/null; then
    echo "Installing gdown..."
    pip install gdown
fi

# Download model weights
cd "$MODEL_DIR"
gdown --id 1CuSUYUF0uTbcANFRffzoMUllCP8Du-HT

# Unzip models
if [ -f "panel_extraction_models.zip" ]; then
    echo "Extracting models..."
    unzip -o panel_extraction_models.zip
    rm panel_extraction_models.zip
    echo "Models extracted to $MODEL_DIR"
else
    echo "Error: Download failed or file not found"
    exit 1
fi

cd ../..
echo "Done! Models are in $MODEL_DIR"
