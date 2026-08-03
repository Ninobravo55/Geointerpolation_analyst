#!/usr/bin/env python3
"""
package_plugin.py — Script para empaquetar GeoInterpolation Analyst en un archivo .ZIP
listo para publicar o instalar en QGIS.

Excluye automáticamente carpetas de desarrollo (tests/, .git/, __pycache__, etc.).
"""

import os
import sys
import zipfile
from pathlib import Path

# Nombres y patrones a ignorar
IGNORED_DIRS = {
    ".git", ".github", ".vscode", ".idea", ".pytest_cache",
    "__pycache__", "tests"
}

IGNORED_EXTS = {
    ".pyc", ".pyo", ".pyd", ".zip"
}

IGNORED_FILES = {
    ".gitignore", ".pb_ignore", "package_plugin.py"
}


def get_version(plugin_dir: Path) -> str:
    metadata_file = plugin_dir / "metadata.txt"
    if not metadata_file.exists():
        return "1.0"
    with open(metadata_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("version="):
                return line.strip().split("=", 1)[1]
    return "1.0"


def build_zip():
    plugin_dir = Path(__file__).resolve().parent
    plugin_name = plugin_dir.name  # "GeoInterpolation_Analyst"
    version = get_version(plugin_dir)
    zip_name = f"{plugin_name}.zip"
    zip_path = plugin_dir.parent / zip_name

    print(f"[*] Empaquetando plugin: {plugin_name} v{version}")
    print(f"[*] Directorio origen: {plugin_dir}")
    print(f"[*] Archivo destino: {zip_path}")
    print("-" * 60)

    included_count = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_dir):
            root_path = Path(root)
            rel_root = root_path.relative_to(plugin_dir)

            # Filtrar carpetas ignoradas
            dirs[:] = [
                d for d in dirs
                if d not in IGNORED_DIRS and not d.startswith(".")
            ]

            # Verificar si la ruta actual esta dentro de una carpeta ignorada
            parts = rel_root.parts
            if any(p in IGNORED_DIRS for p in parts):
                continue

            for file in sorted(files):
                file_path = root_path / file
                suffix = file_path.suffix.lower()

                if suffix in IGNORED_EXTS or file in IGNORED_FILES or file.startswith("."):
                    continue

                # Ruta dentro del zip: GeoInterpolation_Analyst/...
                arcname = Path(plugin_name) / rel_root / file
                zf.write(file_path, str(arcname))
                print(f"  + {arcname}")
                included_count += 1

    print("-" * 60)
    size_kb = zip_path.stat().st_size / 1024
    print(f"[OK] Paquete creado exitosamente: {zip_path}")
    print(f"[*] Total de archivos incluidos: {included_count}")
    print(f"[*] Tamaño del archivo: {size_kb:.1f} KB")


if __name__ == "__main__":
    build_zip()
