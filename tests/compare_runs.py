"""
Compare two runs: did a change alter any paper's result?

    python tests/compare_runs.py output_before output_after

Reads summary.csv from each folder and lists every paper whose verdict, openness or datasets differ.
Use it after changing the code: run the pipeline into a new folder (DV_OUT_DIR=output_after), then
compare with the folder from before the change. No differences = the change did not move any result.
Exit code 1 when something differs, so it can also be used in a script.
"""
import csv, os, sys

# columns that make up the result; the rest (notes, signals, field) are shown only with --all
RESULT = ("data_verdict", "openness", "datasets", "reuses_data")


def load(folder):
    path = os.path.join(folder, "summary.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["paper"]: r for r in csv.DictReader(f)}


def main(before_dir, after_dir, show_all=False):
    before, after = load(before_dir), load(after_dir)
    cols = None
    changed = 0
    for paper in sorted(set(before) | set(after)):
        b, a = before.get(paper), after.get(paper)
        if b is None or a is None:
            print(f"{paper}: only in {'after' if b is None else 'before'}")
            changed += 1
            continue
        cols = cols or ([c for c in a if c in b] if show_all else [c for c in RESULT if c in a and c in b])
        diffs = [(c, b[c], a[c]) for c in cols if b[c] != a[c]]
        if diffs:
            changed += 1
            print(paper)
            for c, old, new in diffs:
                print(f"  {c}:\n    before: {old}\n    after:  {new}")
    n = len(set(before) | set(after))
    print(f"\n{changed} of {n} papers differ" + ("" if show_all else " (verdict, openness, datasets, reuse; --all for every column)"))
    sys.exit(1 if changed else 0)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--all"]
    if len(args) != 2:
        sys.exit(__doc__)
    main(*args, show_all="--all" in sys.argv)
