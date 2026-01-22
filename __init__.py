import threading
import os
import sys

# Ajoute le chemin de l'application au sys.path pour permettre les imports dans run.py
APP_PATH = os.path.dirname(__file__)
if APP_PATH not in sys.path:
    sys.path.append(APP_PATH)

from .run import main  # noqa: E402
from . import controllers  # noqa: E402, F401

# Démarre la boucle de planification de run.py dans un thread séparé
# Le mode daemon=True permet au thread de s'arrêter quand le serveur s'arrête
threading.Thread(target=main, daemon=True).start()
