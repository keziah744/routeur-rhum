"""Tâche planifiée n° 2 : python scripts/ensemble.py (31 scénarios GEFS, route la plus sûre). Journal : logs/routeur.log."""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# pythonw (tâche planifiée, sans console) : pas de stdout/stderr, on les envoie dans un fichier.
if sys.stdout is None or sys.stderr is None:
    (ROOT / "logs").mkdir(exist_ok=True)
    out = open(ROOT / "logs" / "tache-planifiee.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or out
    sys.stderr = sys.stderr or out

from routeur.__main__ import main  # noqa: E402

try:
    sys.exit(main(["ensemble", *sys.argv[1:]]))
except SystemExit:
    raise
except BaseException:
    traceback.print_exc()
    sys.exit(1)
