"""Собирает нативные модули raster.pyx и mesher.pyx: python build_raster.py"""
import subprocess
import sys
import sysconfig
from pathlib import Path

root = Path(__file__).parent

for name in ("raster", "mesher"):
    target = root / f"{name}{sysconfig.get_config_var('EXT_SUFFIX')}"

    subprocess.run(
        [sys.executable, "-m", "cython", "-3", f"{name}.pyx", "-o", f"{name}.c"],
        cwd=root,
        check=True
    )

    subprocess.run(
        [
            "clang", "-O3", "-shared", "-fPIC",
            "-undefined", "dynamic_lookup",
            f"-I{sysconfig.get_paths()['include']}",
            f"{name}.c", "-o", target.name
        ],
        cwd=root,
        check=True
    )

    (root / f"{name}.c").unlink()

    print(f"built {target.name}")
