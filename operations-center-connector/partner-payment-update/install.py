"""Install the portal connector into the supplied Operations Center code version.

The package contains only code/templates. It never copies or changes a data folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent
MANIFEST = PACKAGE / "manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choose_folder() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1].strip('"')).expanduser().resolve()
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        picked = filedialog.askdirectory(title="Choose your existing TPF_ADMIN folder")
        root.destroy()
        if picked:
            return Path(picked).resolve()
    except Exception:
        pass
    entered = input("Paste the full path to your existing TPF_ADMIN folder: ").strip()
    if not entered:
        raise ValueError("No folder selected. Nothing changed.")
    return Path(entered.strip('"')).expanduser().resolve()


def install(folder: Path) -> str:
    if not (folder / "ui" / "app.py").is_file() and (folder / "TPF_ADMIN" / "ui" / "app.py").is_file():
        folder = folder / "TPF_ADMIN"
    if not (folder / "ui" / "app.py").is_file():
        raise ValueError("This is not a TPF_ADMIN folder (ui/app.py is missing). Nothing changed.")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["files"]
    planned = []
    for item in entries:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid update package path. Nothing changed.")
        source = PACKAGE / "payload" / relative
        target = folder / relative
        if not source.is_file() or digest(source) != item["new_sha256"]:
            raise ValueError("Update package failed its checksum. Nothing changed.")
        current = digest(target) if target.is_file() else None
        if current == item["new_sha256"]:
            continue
        if current not in item.get("accepted_old_sha256", [item["old_sha256"]]):
            raise ValueError(f"{relative} differs from the tested Admin version. Nothing changed.")
        planned.append((relative, source, target))
    if not planned:
        return "Already updated. Nothing changed."

    backup = folder / "update-backups" / ("partner-portal-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True, exist_ok=False)
    for relative, _, target in planned:
        if target.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    (backup / "changed-files.json").write_text(json.dumps([str(p) for p, _, _ in planned], indent=2), encoding="utf-8")
    written = []
    try:
        for relative, source, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".portal-update-tmp")
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            written.append((relative, target))
    except Exception:
        for relative, target in reversed(written):
            saved = backup / relative
            if saved.is_file():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise
    return f"Updated {len(planned)} code files in {folder}. Backup: {backup}"


if __name__ == "__main__":
    try:
        print(install(choose_folder()))
        print("No data folders, credentials, or pool records were copied or changed.")
    except Exception as error:
        print("UPDATE STOPPED:", error)
        sys.exit(1)
