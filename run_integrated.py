"""
INTEGRATED pipeline (Version B) -- the wrapper.

Runs DFP live on a PDF folder (via dfp_live), then feeds its CSV into the SAME core pipeline
as the consumer version. One command, starting from just a folder of PDFs.

    # simplest: pass the PDF folder, let everything else default
    python run_integrated.py  path/to/pdfs

    # or set it (and optionally the DFP location / model) via environment variables
    set DV_PDF_DIR=path/to/pdfs
    set DV_DFP_DIR=path/to/datasets-from-pdf
    set DV_MODEL=qwen3.5
    python run_integrated.py

Versions, side by side:
  run_pipeline.py   (A, consumer)   -- you supply a precomputed DFP CSV. No DFP install needed.
  run_integrated.py (B, wrapper)    -- this runs DFP for you, then the identical core.

The ONLY difference is where the DFP CSV comes from. Detect/verify/classify/fuse are shared, so
both versions produce the same outputs, including merged_output.csv -- a strict superset of a DFP
row (DFP's columns verbatim + dv_* additions, with dv_disagreement flagging where the tools differ).

RUN THIS WITH DFP's PYTHON/VENV so DFP (and PyMuPDF) import cleanly. Text for the regex detector
is extracted from the PDFs with DFP's own extractor -- so a fresh machine needs only the PDFs.
"""
import os, sys
import config; config.load_env()   # read a local .env into os.environ before the DV_* vars below
import dfp_live, run_pipeline

# --- configure (env var > CLI arg > default); edit the defaults or just set the env vars --------
PDF_DIR    = (sys.argv[1] if len(sys.argv) > 1 else
              os.environ.get("DV_PDF_DIR", r"path/to/pdfs"))
MODEL      = os.environ.get("DV_MODEL", "")             # empty -> DFP uses VLM_MODEL from its .env (litellm)
BACKEND    = os.environ.get("DV_BACKEND", "litellm")    # 'litellm' (HPC proxy) or 'ollama' (local)
OUT_DIR    = os.environ.get("DV_OUT_DIR",
                            os.path.join(os.path.dirname(__file__), "output_integrated"))
TEXT_DIR   = os.path.join(OUT_DIR, "_text")              # .txt auto-extracted from the PDFs
DFP_CSV    = os.path.join(OUT_DIR, "dfp_output.csv")
CACHE      = os.path.join(os.path.dirname(__file__), ".verify_cache.json")
# DV_DFP_DIR (where datasets-from-pdf lives) is read inside dfp_live.
# ------------------------------------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.isdir(PDF_DIR):
        sys.exit(f"PDF_DIR not found: {PDF_DIR}\nPass it as an argument or set DV_PDF_DIR.")

    print(f"STAGE 0a extract text (DFP's extractor) from {PDF_DIR}:")
    dfp_live.extract_texts(PDF_DIR, TEXT_DIR)

    print("STAGE 0b run DFP (live):")
    use_no_refs = os.environ.get("DV_NO_REFS", "").lower() in ("1", "true", "yes")
    dfp_live.run_dfp(PDF_DIR, DFP_CSV, model=(MODEL or None), backend=BACKEND,
                     no_references=use_no_refs)          # produces DFP_CSV (vanilla DFP output)

    run_pipeline.main(text_dir=TEXT_DIR, dfp_csv=DFP_CSV, out_dir=OUT_DIR, cache=CACHE)

if __name__ == "__main__":
    main()
