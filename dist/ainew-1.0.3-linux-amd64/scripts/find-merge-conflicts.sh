#!/bin/bash
# Merge conflict marker'larını bulur (<<<<<<<, =======, >>>>>>>)
set -e
ROOT="${1:-.}"
echo "Conflict aranıyor: $ROOT"
echo "---"
FOUND=0
while IFS= read -r -d '' f; do
  if grep -q "^<<<<<<< " "$f" 2>/dev/null; then
    echo "CONFLICT: $f"
    grep -n "^<<<<<<< \|^======= \|^>>>>>>> " "$f" 2>/dev/null || true
    echo ""
    FOUND=1
  fi
done < <(find "$ROOT" -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.yml" -o -name "*.yaml" -o -name "*.json" -o -name "*.md" -o -name "*.sh" \) ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/docs/MERGE_CONFLICT*" -print0 2>/dev/null)
if [ "$FOUND" -eq 0 ]; then
  echo "Hiç conflict marker bulunamadı."
fi
