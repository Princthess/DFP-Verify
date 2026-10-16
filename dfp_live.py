"""
DFP LIVE adapter -- runs the datasets-from-pdf (DFP) detector on a PDF folder and returns the
path to a single CSV, so the integrated pipeline can consume it like any run.

This is the ONLY place that knows how to invoke DFP. Everything downstream is identical to
the consumer version (run_pipeline.py); the two pipelines differ only in where the DFP CSV
comes from -- you ran it by hand (consumer) vs. this runs it for you (integrated).

It shells out to DFP's own CLI and modifies NO DFP code. One step:
    python -m main --batch-dir <pdfs> --csv <out.csv> --backend {litellm|ollama}

It can also extract plain .txt per PDF (via DFP's OWN extractor) for the regex detector, so a
fresh machine needs only the PDFs -- no separate .txt corpus.

IMPORTANT: run this with DFP's Python/venv (so `import extract_dataset...` and PyMuPDF resolve).
Set DFP_DIR (or env DV_DFP_DIR) and the model to match your install.
"""
import os, sys, glob, subprocess

# --- configure to your install (env overrides let you avoid editing code on another machine) ---
DFP_DIR = os.environ.get("DV_DFP_DIR", r"path/to/datasets-from-pdf")
PYTHON  = sys.executable          # the interpreter running this (DFP must be importable by it)
MODEL   = os.environ.get("DV_MODEL", "qwen3.5")   # DFP's default local Ollama model; change to your tag
# ------------------------------------------------------------------------------------------------

def run_dfp(pdf_dir, out_csv, model=None, dfp_dir=None, backend="litellm",
            enrich_urls=False, no_ocr=False, no_references=False, extra=None):
    """Run DFP over `pdf_dir` -> `out_csv` using DFP's ONE-STEP CSV output
    (`python -m main --batch-dir ... --csv ... --backend ...`). Returns out_csv on success.
    backend 'litellm' hits the HPC LiteLLM proxy (base URL/key from DFP's own .env);
    'ollama' uses a local model. Reuses an existing CSV if it is newer than every PDF (the LLM step is slow)."""
    dfp_dir = dfp_dir or DFP_DIR
    if _fresh(out_csv, pdf_dir):
        print(f"  DFP: reusing {out_csv} (newer than the PDFs)")
        return out_csv
    if not os.path.isdir(dfp_dir):
        raise FileNotFoundError(f"DFP not found at {dfp_dir}. Set DFP_DIR / env DV_DFP_DIR.")
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    if os.path.exists(out_csv):
        os.remove(out_csv)          # DFP's --csv APPENDS; start clean so rows aren't duplicated

    # one step now: PDFs -> one CSV (the slow, LLM step). --model omitted for litellm so DFP
    # uses VLM_MODEL from its .env; pass it only to override.
    cmd = [PYTHON, "-m", "main", "--batch-dir", pdf_dir, "--csv", os.path.abspath(out_csv),
           "--backend", backend]
    if model:         cmd += ["--model", model]
    if enrich_urls:   cmd.append("--enrich-urls")
    if no_ocr:        cmd.append("--no-ocr")
    if no_references: cmd.append("--no-references")
    if extra:         cmd += list(extra)
    print(f"  DFP: {' '.join(cmd)}")
    rc = subprocess.run(cmd, cwd=dfp_dir).returncode
    if not os.path.exists(out_csv):
        raise RuntimeError("DFP produced no CSV -- check the LLM backend (Ollama up, or the LiteLLM "
                           "endpoint reachable on the right network/VPN) and the model tag.")
    if rc != 0:
        # DFP returns 1 if ANY single PDF failed, even when the rest wrote rows. Continue with what we got.
        print(f"  DFP: WARNING exit={rc} but {out_csv} was written -- "
              f"some PDFs may have failed; continuing with what succeeded.")
    return out_csv

def _longpath(path):
    r"""On Windows, prefix with \\?\ to bypass the 260-char MAX_PATH limit (long paper
    filenames under a deep output dir otherwise fail with 'No such file or directory')."""
    if os.name == "nt":
        ap = os.path.abspath(path)
        return ap if ap.startswith("\\\\?\\") else "\\\\?\\" + ap
    return path

def extract_texts(pdf_dir, text_dir, dfp_dir=None, ocr=True):
    """Write <stem>.txt for every PDF using DFP's OWN extractor, so the regex detector sees
    exactly the text DFP reads. Needs DFP importable (run inside DFP's venv). Reuses fresh .txt.
    Returns text_dir. No-op-safe: skips PDFs whose .txt is newer than the PDF."""
    dfp_dir = dfp_dir or DFP_DIR
    os.makedirs(text_dir, exist_ok=True)
    if dfp_dir not in sys.path:
        sys.path.insert(0, dfp_dir)
    try:
        from extract_dataset.pdf import extract_text
    except Exception as e:
        raise RuntimeError(
            f"Could not import DFP's text extractor ({e}). Run this with DFP's Python/venv, "
            f"or set TEXT_DIR to a folder of pre-extracted .txt files.")
    pdfs = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))
    made = reused = failed = 0
    for pdf in pdfs:
        stem = os.path.splitext(os.path.basename(pdf))[0]
        txt = os.path.join(text_dir, stem + ".txt")
        lp = _longpath(txt)
        if os.path.exists(lp) and os.path.getmtime(lp) >= os.path.getmtime(pdf):
            reused += 1; continue
        try:
            text, _ = extract_text(pdf, ocr_fallback=ocr)
            with open(lp, "w", encoding="utf-8") as fh:
                fh.write(text)
            made += 1
        except Exception as e:
            failed += 1
            print(f"  text: WARNING failed to extract {os.path.basename(pdf)}: {e}")
    msg = f"  text: {made} written, {reused} reused of {len(pdfs)} PDFs in {text_dir}"
    if failed:
        msg += f"  -- {failed} FAILED (those papers will be DFP-only!)"
    print(msg)
    return text_dir

def _fresh(csv_path, pdf_dir):
    if not os.path.exists(csv_path):
        return False
    try:
        newest_pdf = max((os.path.getmtime(p) for p in glob.glob(os.path.join(pdf_dir, "*.pdf"))),
                         default=0)
        return os.path.getmtime(csv_path) >= newest_pdf
    except OSError:
        return False
