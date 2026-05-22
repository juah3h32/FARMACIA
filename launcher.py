import subprocess
import os
import sys

SRC     = r"C:\Users\Jereth\Documents\FARMACIA"
MAIN_PY = os.path.join(SRC, "main.py")

PYTHON_CANDIDATES = [
    r"C:\Users\Jereth\AppData\Local\Programs\Python\Python312\pythonw.exe",
    r"C:\Users\Jereth\AppData\Local\Programs\Python\Python313\pythonw.exe",
    r"C:\Users\Jereth\AppData\Local\Programs\Python\Python311\pythonw.exe",
    r"C:\Python312\pythonw.exe",
    r"C:\Python313\pythonw.exe",
]


def find_python():
    # Try shutil.which first (works when PATH is set)
    try:
        import shutil
        found = shutil.which("pythonw") or shutil.which("python")
        if found and os.path.exists(found):
            return found
    except Exception:
        pass
    # Fallback: hardcoded candidates
    for c in PYTHON_CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def show_error(msg):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Farmacia Eben-Ezer — Error", msg)
        root.destroy()
    except Exception:
        pass


def main():
    if not os.path.exists(MAIN_PY):
        show_error(
            f"No se encontró el archivo principal:\n{MAIN_PY}\n\n"
            "Verifica que la carpeta FARMACIA no haya sido movida."
        )
        return

    python = find_python()
    if not python:
        show_error(
            "No se encontró Python instalado.\n"
            "Instala Python 3.10+ desde python.org"
        )
        return

    try:
        subprocess.Popen([python, MAIN_PY], cwd=SRC)
    except Exception as e:
        show_error(f"Error al iniciar la aplicación:\n{e}")


main()
