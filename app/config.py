"""Where Print Studio finds its helpers on this computer.

Defaults work for an install made by setup (everything inside the Print Studio folder). Anything can be
overridden in settings.json in the Print Studio folder (written by the installer), e.g.:
    {"wangp_dir": "D:/Wan2GP", "ollama_model": "gemma4:12b", "creality_exe": "C:/.../CrealityPrint.exe"}
"""
import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT / "settings.json"


def _settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))   # PowerShell 5 writes a BOM
    except (OSError, ValueError):
        return {}


S = _settings()


def _wangp_dir():
    for p in (S.get("wangp_dir"), os.environ.get("PRINT_STUDIO_WANGP"), ROOT / "engine" / "Wan2GP", ROOT.parent / "Wan2GP"):
        if p and (Path(p) / "wgp.py").is_file():
            return Path(p)
    return ROOT / "engine" / "Wan2GP"


def _creality():
    if S.get("creality_exe") and Path(S["creality_exe"]).is_file():
        return Path(S["creality_exe"])
    found = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            found += glob.glob(os.path.join(base, "Creality", "Creality Print*", "CrealityPrint.exe"))
    return Path(sorted(found)[-1]) if found else None   # newest version wins


WANGP = _wangp_dir()
WANGP_PY = WANGP / "env_venv" / "Scripts" / "python.exe"
OLLAMA_URL = S.get("ollama_url", "http://127.0.0.1:11434")
OLLAMA_MODEL = S.get("ollama_model", "gemma4:12b")
CREALITY = _creality()
