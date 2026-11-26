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

# Lookups that got no answer this run (rate limit, server error, network). Such an answer is never
# cached, and run_pipeline.py reports the count (screen + run_info.json -> report) instead of letting
# "no answer" pass for "nothing there".
FAILED = []

def transient(status):
    """True for answers that mean "ask again later", not "there is nothing": 429 and 5xx."""
    return status == 429 or status >= 500

def failed(what):
    FAILED.append(what)
