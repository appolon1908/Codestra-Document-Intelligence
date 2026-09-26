"""Regenerate the committed OpenAPI contract (openapi.json)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_openapi import current_openapi  # noqa: E402

(ROOT / "openapi.json").write_text(json.dumps(current_openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("wrote openapi.json")
