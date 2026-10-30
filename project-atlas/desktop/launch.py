"""Entry point for the packaged Project Atlas desktop application."""
import multiprocessing
import sys

from project_atlas.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
