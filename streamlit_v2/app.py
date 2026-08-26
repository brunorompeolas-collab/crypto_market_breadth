"""Streamlit Community Cloud entrypoint for the isolated Breadth v2 preview."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_v2 import main


if __name__ == "__main__":
    main()
