#!/usr/bin/env bash
set -euo pipefail

# Script to build twgpu-map-photography and twmap-fix binaries if not present.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TWGPU_BIN="$ROOT_DIR/twgpu/target/release/twgpu-map-photography"
TWMAP_BIN="$ROOT_DIR/twmap/target/release/twmap-fix"

mkdir -p "$ROOT_DIR/bin"

if [[ ! -f "$TWGPU_BIN" && ! -f "$ROOT_DIR/bin/twgpu-map-photography" ]]; then
    echo "Building twgpu-map-photography..."
    if [[ ! -d "$ROOT_DIR/twgpu" ]]; then
        git clone https://gitlab.com/ddnet-rs/twgpu.git "$ROOT_DIR/twgpu"
    fi
    (cd "$ROOT_DIR/twgpu/twgpu-tools" && cargo build --release)
fi

if [[ ! -f "$TWMAP_BIN" && ! -f "$ROOT_DIR/bin/twmap-fix" ]]; then
    echo "Building twmap-fix..."
    if [[ ! -d "$ROOT_DIR/twmap" ]]; then
        git clone https://gitlab.com/ddnet-rs/twmap.git "$ROOT_DIR/twmap"
    fi
    (cd "$ROOT_DIR/twmap/twmap-tools" && cargo build --release)
fi

# Copy binaries to bin/ if present in target/release
if [[ -f "$TWGPU_BIN" ]]; then
    cp "$TWGPU_BIN" "$ROOT_DIR/bin/twgpu-map-photography"
fi
if [[ -f "$TWMAP_BIN" ]]; then
    cp "$TWMAP_BIN" "$ROOT_DIR/bin/twmap-fix"
fi

echo "Checking built tools..."
ls -la "$ROOT_DIR/bin/twgpu-map-photography" "$ROOT_DIR/bin/twmap-fix" || true
