"""Package locked Linux/Python 3.12 wheels without Docker or local credentials."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / ".build"
    output.mkdir(exist_ok=True)
    requirements = output / "requirements.txt"
    subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project",
                    "--format", "requirements-txt", "--output-file", str(requirements)],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix="imhungry-lambda-") as directory:
        target = Path(directory)
        subprocess.run(["uv", "pip", "install", "--python-version", "3.12",
                        "--python-platform", "x86_64-manylinux_2_28", "--only-binary", ":all:",
                        "--require-hashes", "--target", str(target), "-r", str(requirements)], check=True)
        shutil.copytree(ROOT / "src", target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        shutil.copyfile(ROOT / "infra/run.sh", target / "run.sh")
        (target / "run.sh").chmod(0o755)
        archive = output / "backend.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(target.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    bundle.write(path, path.relative_to(target))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "artifact-key.txt").write_text(f"artifacts/backend/{digest}.zip\n")
    print(f"Built {archive} ({archive.stat().st_size:,} bytes); SHA256 {digest}")


if __name__ == "__main__":
    main()
