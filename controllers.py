from ansi2html import Ansi2HTMLConverter
from py4web import action
import os

# Chemin vers le dossier de l'application
APP_PATH = os.path.dirname(__file__)
LOG_FILE = os.path.join(APP_PATH, "logs", "hotelrates.log")

@action("index")
def index():
    """Charge la page d'index qui affiche les logs."""
    if not os.path.exists(LOG_FILE):
        return f"Aucun fichier de log trouvé à {LOG_FILE}"

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            # Récupérer les 100 dernières lignes
            lines = f.readlines()[-100:]
            content = "".join(lines)
    except Exception as e:
        return f"Erreur lors de la lecture des logs: {e}"

    conv = Ansi2HTMLConverter(dark_bg=True)
    html_content = conv.convert(content)

    # Retourne les logs dans une balise <pre> pour garder le formatage
    return f"""
    <html>
        <head>
            <title>HotelRates Logs</title>
            <meta http-equiv="refresh" content="5">
            <style>
                body {{ background-color: #111; color: #eee; font-family: monospace; padding: 20px; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
    </html>
    """
