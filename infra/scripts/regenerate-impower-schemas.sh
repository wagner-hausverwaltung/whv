#!/usr/bin/env bash
# Regenerate backend/app/integrations/impower/_schemas_generated.py from the
# live Impower OpenAPI spec. See ADR-0003.
#
# Prereqs:
#   - node (for npx)
#   - uv installed and the backend venv synced (`cd backend && uv sync`)
#
# Run from repo root:
#   ./infra/scripts/regenerate-impower-schemas.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC_URL="${IMPOWER_SPEC_URL:-https://api.app.impower.de/v2/api-docs}"
SPEC_SWAGGER2="/tmp/impower.swagger2.json"
SPEC_OPENAPI3="/tmp/impower.openapi3.json"
OUT="$ROOT/backend/app/integrations/impower/_schemas_generated.py"

echo "==> fetching Swagger 2 spec from $SPEC_URL"
curl -sf --max-time 30 "$SPEC_URL" -o "$SPEC_SWAGGER2"

echo "==> converting Swagger 2 → OpenAPI 3 (via swagger2openapi)"
NPM_CONFIG_CACHE="/tmp/npm-cache" npx -y -p swagger2openapi swagger2openapi "$SPEC_SWAGGER2" -o "$SPEC_OPENAPI3"

echo "==> generating Pydantic v2 models with datamodel-code-generator"
cd "$ROOT/backend"
uv run datamodel-codegen \
    --input "$SPEC_OPENAPI3" \
    --input-file-type openapi \
    --output "$OUT" \
    --target-python-version 3.12 \
    --use-standard-collections \
    --use-union-operator \
    --output-model-type pydantic_v2.BaseModel \
    --field-constraints \
    --use-field-description \
    --reuse-model \
    --use-schema-description

echo "==> patching AwareDatetime → datetime (Impower returns naïve timestamps)"
sed -i.bak 's/AwareDatetime/datetime/g' "$OUT"
sed -i.bak 's/from pydantic import datetime, BaseModel, Field/from datetime import datetime\nfrom pydantic import BaseModel, Field/' "$OUT"
rm -f "${OUT}.bak"

echo "==> done. Inspect with: git diff $OUT"
