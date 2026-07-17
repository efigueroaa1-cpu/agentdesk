# Runtime hook PyInstaller: carga .env desde el directorio del exe.
# Se ejecuta ANTES de cualquier importacion del programa principal.
# Garantiza que os.environ tenga todas las variables (MASTER_PASSWORD_HASH,
# API keys, AGENTDESK_JWT_SECRET, etc.) independientemente del cwd.
import sys
import os
from pathlib import Path

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent
    _env_file = _exe_dir / ".env"
    if _env_file.exists():
        try:
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val
        except Exception:
            pass
