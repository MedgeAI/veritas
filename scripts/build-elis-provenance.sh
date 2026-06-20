#!/bin/bash
# Build the veritas-elis-provenance Docker image from ELIS source.
#
# This script builds the provenance-analysis container from the ELIS submodule.
# The resulting image is tagged as veritas-elis-provenance:latest and can be
# used by engine/static_audit/tools/_elis_provenance_runner.py.
#
# Usage:
#   ./scripts/build-elis-provenance.sh
#
# Prerequisites:
#   - Docker installed and running
#   - third_party/elis submodule initialized
#
# The image exposes a Python CLI that accepts JSON input via stdin or file
# and writes JSON output to stdout or file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ELIS_PROVENANCE_DIR="$PROJECT_ROOT/third_party/elis/system_modules/provenance-analysis"
IMAGE_NAME="veritas-elis-provenance"
IMAGE_TAG="latest"

echo "Building $IMAGE_NAME:$IMAGE_TAG from ELIS provenance-analysis..."

# Check if ELIS submodule exists
if [ ! -d "$ELIS_PROVENANCE_DIR" ]; then
    echo "ERROR: ELIS provenance-analysis directory not found at:"
    echo "  $ELIS_PROVENANCE_DIR"
    echo ""
    echo "Please initialize the submodule:"
    echo "  git submodule update --init --recursive"
    exit 1
fi

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed or not in PATH"
    exit 1
fi

# Build the image
cd "$ELIS_PROVENANCE_DIR"
docker build -t "$IMAGE_NAME:$IMAGE_TAG" .

echo ""
echo "✓ Successfully built $IMAGE_NAME:$IMAGE_TAG"
echo ""
echo "Verify the image:"
echo "  docker images | grep $IMAGE_NAME"
echo ""
echo "Test the image:"
echo "  docker run --rm $IMAGE_NAME:$IMAGE_TAG --help"
