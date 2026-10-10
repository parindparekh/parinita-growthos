"""Explicit, private connector credentials for the loopback launcher."""
import json
import re
from pathlib import Path


def load_connector_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(values, dict):
        raise ValueError("Local connector credentials must be a JSON object")
    # Validate the entire file before returning anything. Never echo values.
    for name, value in values.items():
        if not re.fullmatch(r"GROWTHOS_SECRET_[A-Z0-9_]+", name):
            raise ValueError("Local connector credentials accept only GROWTHOS_SECRET_* names")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Local connector credentials must be nonempty strings")
    return values
