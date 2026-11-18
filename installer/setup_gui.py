"""Windows Setup Wizard for SiliconForge VLSI Studio."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import winreg
import zipfile

APP_NAME = "SiliconForge VLSI Studio"
EXE_NAME = "SiliconForgeVLSI.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\SiliconForgeVLSI"


def _payload_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload.zip"


def _create_shortcut(lnk_path: Path, target_exe: Path, work_dir: Path, icon_path: Path) -> None:
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{str(lnk_path).replace(chr(39), chr(39)*2)}'); "
        f"$sc.TargetPath = '{str(target_exe).replace(chr(39), chr(39)*2)}'; "
        f"$sc.WorkingDirectory = '{str(work_dir).replace(chr(39), chr(39)*2)}'; "
        f"$sc.IconLocation = '{str(icon_path).replace(chr(39), chr(39)*2)},0'; "
        "$sc.Description = 'SiliconForge VLSI Studio - RTL, Synthesis & Layout'; "
        "$sc.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _write_uninstaller(install_dir: Path, desktop_lnk: Path, start_lnk: Path) -> Path:
    uninst = install_dir / "uninstall.bat"
    uninst.write_text(
        "@echo off\n"
        f'del /f /q "{desktop_lnk}" 2>nul\n'
        f'del /f /q "{start_lnk}" 2>nul\n'
        f'reg delete "HKCU\\{UNINSTALL_KEY}" /f 2>nul\n'
        f'start "" cmd /c "timeout /t 2 >nul & rmdir /s /q \\"{install_dir}\\""\n',
        encoding="utf-8",
    )
    return uninst


def _register_uninstall(install_dir: Path, exe_path: Path, uninst_path: Path) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "0.1.0")
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "SiliconForge")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe_path))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd /c "{uninst_path}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} — Setup")
        self.geometry("540x360")
        self.resizable(False, False)
        self.configure(bg="#12151B")

        default_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "SiliconForgeVLSI"
        self.dir_var = tk.StringVar(value=str(default_dir))
        self.desktop_var = tk.BooleanVar(value=True)
        self.startmenu_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready to install SiliconForge VLSI Studio.")

        self._build_ui()

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg="#1A1E26", height=70)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text=f"Install {APP_NAME}", fg="#E6EDF3", bg="#1A1E26",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", padx=20, pady=(12, 2))
        tk.Label(
            hdr, text="Standalone RTL Simulation · Synthesis & Schematic · Magic Layout & DRC",
            fg="#38BDF8", bg="#1A1E26", font=("Segoe UI", 9),
        ).pack(anchor="w", padx=20)

        body = tk.Frame(self, bg="#12151B", padx=20, pady=16)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Destination Folder:", fg="#E6EDF3", bg="#12151B", font=("Segoe UI", 10)).pack(anchor="w")
        row = tk.Frame(body, bg="#12151B")
        row.pack(fill="x", pady=(4, 12))
        tk.Entry(
            row, textvariable=self.dir_var, bg="#1A1E26", fg="#E6EDF3",
            insertbackground="#E6EDF3", relief="flat", font=("Consolas", 9),
        ).pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        tk.Button(
            row, text="Browse...", command=self._browse, bg="#222732", fg="#E6EDF3",
            relief="flat", padx=12, pady=4,
        ).pack(side="right")

        for text, var in (
            ("Create a Desktop shortcut", self.desktop_var),
            ("Create a Start Menu shortcut", self.startmenu_var),
            ("Launch SiliconForge VLSI Studio after installation", self.launch_var),
        ):
            tk.Checkbutton(
                body, text=text, variable=var, bg="#12151B", fg="#E6EDF3",
                selectcolor="#1A1E26", activebackground="#12151B", activeforeground="#E6EDF3",
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=2)

        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(14, 4))
        tk.Label(body, textvariable=self.status_var, fg="#8B949E", bg="#12151B", font=("Segoe UI", 9)).pack(anchor="w")

        footer = tk.Frame(self, bg="#1A1E26", height=52)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self.btn_cancel = tk.Button(
            footer, text="Cancel", command=self.destroy, bg="#222732", fg="#E6EDF3",
            relief="flat", padx=16, pady=6,
        )
        self.btn_cancel.pack(side="right", padx=(6, 16), pady=10)
        self.btn_install = tk.Button(
            footer, text="Install", command=self._start_install, bg="#3B82F6", fg="#FFFFFF",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=20, pady=6,
        )
        self.btn_install.pack(side="right", pady=10)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get())
        if chosen:
            self.dir_var.set(str(Path(chosen) / "SiliconForgeVLSI"))

    def _start_install(self) -> None:
        self.btn_install.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        threading.Thread(target=self._do_install, daemon=True).start()

    def _do_install(self) -> None:
        try:
            install_dir = Path(self.dir_var.get())
            payload = _payload_path()
            if not payload.exists():
                raise FileNotFoundError(f"Installer payload not found: {payload}")

            self.after(0, lambda: self.status_var.set("Preparing target directory..."))
            if install_dir.exists():
                shutil.rmtree(install_dir, ignore_errors=True)
            install_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(payload, "r") as zf:
                members = zf.infolist()
                total = max(1, len(members))
                for idx, member in enumerate(members, start=1):
                    zf.extract(member, install_dir)
                    if idx % 20 == 0 or idx == total:
                        pct = int((idx / total) * 90)
                        self.after(0, lambda p=pct, i=idx, t=total: (
                            self.progress.configure(value=p),
                            self.status_var.set(f"Extracting files ({i}/{t})..."),
                        ))

            exe_path = install_dir / EXE_NAME
            ico_path = install_dir / "_internal" / "assets" / "siliconforge.ico"
            if not ico_path.exists():
                ico_path = exe_path

            desktop_dir = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
            desktop_lnk = desktop_dir / f"{APP_NAME}.lnk"
            start_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            start_lnk = start_dir / f"{APP_NAME}.lnk"

            self.after(0, lambda: self.status_var.set("Creating shortcuts..."))
            if self.desktop_var.get():
                desktop_dir.mkdir(parents=True, exist_ok=True)
                _create_shortcut(desktop_lnk, exe_path, install_dir, ico_path)
            if self.startmenu_var.get():
                start_dir.mkdir(parents=True, exist_ok=True)
                _create_shortcut(start_lnk, exe_path, install_dir, ico_path)

            uninst_path = _write_uninstaller(install_dir, desktop_lnk, start_lnk)
            _register_uninstall(install_dir, exe_path, uninst_path)

            self.after(0, lambda: (
                self.progress.configure(value=100),
                self.status_var.set("Installation complete!"),
            ))

            if self.launch_var.get() and exe_path.exists():
                subprocess.Popen([str(exe_path)], cwd=str(install_dir))

            self.after(0, lambda: (
                messagebox.showinfo(APP_NAME, f"{APP_NAME} installed successfully!\n\nLocation: {install_dir}"),
                self.destroy(),
            ))
        except Exception as exc:
            self.after(0, lambda e=exc: (
                messagebox.showerror("Installation Failed", str(e)),
                self.btn_install.config(state="normal"),
                self.btn_cancel.config(state="normal"),
            ))


if __name__ == "__main__":
    SetupWizard().mainloop()
