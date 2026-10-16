"""Load a local .env (KEY=VALUE lines) into os.environ, so settings like DV_CONTACT_EMAIL and the
DV_* paths can live in one file instead of being set in the shell every run. A variable already set
in the shell always wins (setdefault). Looks next to this file and in the current directory.

Copy .env.example to .env to use it. run_pipeline.py and run_integrated.py call load_env() at startup.
"""
import os
from pathlib import Path


def load_env(name=".env"):
    for p in (Path(__file__).resolve().parent / name, Path.cwd() / name):
        try:
            if p.is_file():
                for line in p.read_text(encoding="utf-8-sig").splitlines():   # -sig strips any BOM
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and v:
                        os.environ.setdefault(k, v)   # shell-set values win
        except Exception:
            pass
