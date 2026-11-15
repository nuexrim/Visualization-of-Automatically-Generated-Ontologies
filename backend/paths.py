"""프로젝트 안의 데이터 위치."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BIRD = DATA / "bird"
PAPER = DATA / "paper"
