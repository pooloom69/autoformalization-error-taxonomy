#!/bin/bash
source $HOME/.elan/env
source ~/lean_env/bin/activate

echo "=== Step 1: Building Mathlib ==="
cd /ProofBridge/mathlib_project
lake build
if [ $? -ne 0 ]; then
    echo "ERROR: Mathlib build failed. Stopping."
    exit 1
fi
echo "=== Mathlib build complete! ==="

echo "=== Step 2: Starting pipeline ==="
cd /ProofBridge
python error_taxonomy_pipeline.py
echo "=== Pipeline complete! ==="
