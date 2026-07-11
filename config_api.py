import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Priority 1: %APPDATA%\AgentDesk\.env  (installed mode / setup_wizard location)
# Priority 2: CWD search chain          (development mode)
_APPDATA_ENV = Path(os.environ.get("APPDATA", Path.home())) / "AgentDesk" / ".env"

if _APPDATA_ENV.exists():
    load_dotenv(_APPDATA_ENV, override=False)
else:
    load_dotenv(override=False)

API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Only raise at import time in CLI/dev mode.
# In --api mode the FastAPI startup handles a missing key gracefully.
if not API_KEY and "--api" not in sys.argv:
    raise EnvironmentError(
        f"GEMINI_API_KEY no encontrada.\n"
        f"Crea el archivo: {_APPDATA_ENV}\n"
        f"con la línea: GEMINI_API_KEY=tu_clave"
    )
