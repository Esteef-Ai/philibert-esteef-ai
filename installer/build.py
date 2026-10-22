r"""Build "Philibert Setup" for this computer.

    python installer/build.py          release: installs from the GitHub repository
    python installer/build.py --dev    test build: installs from this repo folder
                                       (nothing has to be pushed to try it)

Makes installer/.buildenv (its own Python environment, outside git) on first
use, then runs PyInstaller: dist/Philibert Setup.exe on Windows,
dist/Philibert Setup.app on a Mac (build that one on a Mac - GitHub Actions'
macOS runner works).
"""
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ENV = HERE / ".buildenv"
IS_WIN = sys.platform == "win32"
PY = ENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
# backports.tarfile: setuptools' pkg_resources needs it inside a frozen app
NEEDS = (["pyinstaller==6.16.0", "pywebview==6.2.1", "psutil==7.2.2", "backports.tarfile==1.2.0"]
         + (["pythonnet==3.1.0"] if IS_WIN else []))


def main():
    dev = "--dev" in sys.argv
    if not PY.exists():
        print("making the build environment ...")
        venv.create(ENV, with_pip=True)
    subprocess.run([str(PY), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "-q", *NEEDS], check=True)

    bundle = HERE / "build" / "bundle"
    shutil.rmtree(bundle, ignore_errors=True)
    bundle.mkdir(parents=True)
    shutil.copy2(REPO / "models.json", bundle / "models.json")
    info = json.loads((REPO / "philibert.json").read_text(encoding="utf-8"))
    (bundle / "philibert.json").write_text(json.dumps(info), encoding="utf-8")
    if dev:
        # a test build installs from this folder: nothing is pushed or uploaded
        (bundle / "source.json").write_text(json.dumps({"local": str(REPO)}), encoding="utf-8")

    sep = ";" if IS_WIN else ":"
    name = "Philibert Setup" + (" (dev)" if dev else "")
    args = [str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile",
            "--name", name, "--icon", str(REPO / "setup" / "assets" / "philibert.ico"),
            "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build" / "work"),
            "--specpath", str(HERE / "build"),
            "--add-data", f"{HERE / 'ui'}{sep}ui", "--add-data", f"{bundle}{sep}bundle",
            "--hidden-import", "core", "--hidden-import", "engine", "--hidden-import", "github_auth",
            "--hidden-import", "nd_imagegen",           # this computer's Image Generation rating
            "--paths", str(HERE), "--paths", str(REPO / "app"), str(HERE / "app.py")]
    subprocess.run(args, check=True, cwd=str(HERE))
    out = HERE / "dist" / (name + (".exe" if IS_WIN else ".app"))
    print(f"built {out} ({out.stat().st_size / 1e6:.1f} MB)" if out.exists() else "build finished")


if __name__ == "__main__":
    main()
