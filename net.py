"""
NET - one HTTP session for every registry call (DataCite, Crossref, doi.org, OpenAlex, Swepub, EBI, NCBI).

Registries ask automated clients to say who they are, so every request carries the same User-Agent with
a contact address (DV_CONTACT_EMAIL, from .env). One place to change it. Read at import time, so the
orchestrators load .env (config.load_env) before importing the pipeline modules.
"""
import os
import requests

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
S = requests.Session()
S.headers.update(UA)
