"""Lance l'interface locale depuis n'importe quel dossier : python scripts/serve.py [--port 8765] [--hote 0.0.0.0]."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from routeur.__main__ import main  # noqa: E402

sys.exit(main(["serveur", *sys.argv[1:]]))
