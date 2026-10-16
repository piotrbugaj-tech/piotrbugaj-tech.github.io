"""Generate the synthetic bracketing dataset with ground truth.

Usage: python tools/make_synthetic.py [--out data/synthetic] [--width 2400 --height 1600]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from estatehdr.synthetic import generate_dataset  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--height", type=int, default=1600)
    ap.add_argument("--supersample", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    t = time.time()
    m = generate_dataset(a.out, a.width, a.height, seed=a.seed, supersample=a.supersample)
    print(f"done in {time.time() - t:.1f}s: {[s['name'] for s in m['series']]}")


if __name__ == "__main__":
    main()
