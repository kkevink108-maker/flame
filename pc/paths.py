"""Where files live, both when run as .py files and when packed into FlameBot.exe.

RESOURCE_DIR: built-in read-only files (templates, glyphs, sample) - inside the .exe when packed.
DATA_DIR:     your files (config.json, debug/, your calibrated templates) - next to the .exe.
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else RESOURCE_DIR
