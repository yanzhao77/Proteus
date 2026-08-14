import os
from pathlib import Path


def env_or_file(name: str, default: str = "") -> str:
    direct = os.getenv(name)
    if direct:
        return direct
    file_name = os.getenv(f"{name}_FILE")
    if file_name:
        return Path(file_name).read_text().strip()
    return default
