#!/bin/bash
set -e

echo "🔨 Building extension..."
rm -rf dist
mkdir -p dist

npx esbuild src/background.ts \
  --bundle \
  --outfile=dist/background.js \
  --platform=browser \
  --target=chrome110 \
  --format=iife \
  --minify=false \
  --external:chrome

cp manifest.json src/sidepanel.html src/sidepanel.js dist/

echo "✅ Built successfully to dist/"
ls -lh dist/
