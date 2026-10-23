#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .tools/liara-cli
cp ops/liara-cli/package.json .tools/liara-cli/package.json
cp ops/liara-cli/package-lock.json .tools/liara-cli/package-lock.json
npm ci --prefix .tools/liara-cli --ignore-scripts --no-audit --no-fund
.tools/liara-cli/node_modules/.bin/liara --version
