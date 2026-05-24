"""
Este archivo ya no se usa. Ejecuta el app.py de la raíz del proyecto (con login).

Uso correcto:
  python app.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    print("=" * 60)
    print("AVISO: Usa app.py en la raiz del proyecto (incluye login).")
    print("Iniciando:", ROOT / "app.py")
    print("=" * 60)
    from app import app  # noqa: E402

    app.run(debug=True, host="127.0.0.1", port=5000)
