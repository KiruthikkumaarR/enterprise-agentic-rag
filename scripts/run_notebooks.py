"""Execute the master notebook (which executes milestone notebooks 01-09 in order) and save outputs."""
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NB = Path(__file__).resolve().parent.parent / "notebooks" / "master_execution_notebook.ipynb"

if __name__ == "__main__":
    nb = nbformat.read(NB, as_version=4)
    t = time.time()
    NotebookClient(nb, timeout=None, kernel_name="python3", resources={"metadata": {"path": str(NB.parent)}}).execute()
    nbformat.write(nb, NB)
    print(f"master notebook executed in {(time.time() - t) / 60:.1f} min", file=sys.stderr)
