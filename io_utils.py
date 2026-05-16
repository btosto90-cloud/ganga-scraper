"""IO helpers compartidos entre scraper.py y notify.py."""

import json
import os


def atomic_write_json(path, data, indent=2, ensure_ascii=False):
    """Escribe JSON a `path` de forma atómica: tmp + fsync + rename.

    Evita dejar el archivo destino corrupto si el proceso muere a mitad de
    escritura (timeout del workflow, kill, OOM). El rename es atómico en POSIX.
    """
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
