import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCRIPT = REPOSITORY_ROOT / "deploy" / "archive-backend-release.sh"


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_release_archive_contains_backend_inputs_but_not_frontend_or_secrets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    files = {
        ".dockerignore": "frontend/\n",
        "Dockerfile": "FROM python:3.12-slim\n",
        "README.md": "backend release fixture\n",
        "app/main.py": "app = object()\n",
        "compose.production.yaml": "services: {}\n",
        "compose.staging.yaml": "services: {}\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "uv.lock": "version = 1\n",
        ".env.production": "PASSWORD=not-for-release\n",
        "frontend/dist/assets/app.js": "frontend payload\n",
        "tests/test_example.py": "def test_example(): pass\n",
    }
    for relative_path, contents in files.items():
        path = source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    _git(source, "init", "--quiet")
    _git(source, "add", "--all")
    _git(
        source,
        "-c",
        "user.name=Archive Test",
        "-c",
        "user.email=archive-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    commit = _git(source, "rev-parse", "HEAD")
    release = tmp_path / "release"
    release.mkdir()

    result = subprocess.run(
        ["bash", str(ARCHIVE_SCRIPT), str(source), commit, str(release)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (release / "Dockerfile").is_file()
    assert (release / "README.md").is_file()
    assert (release / "app/main.py").is_file()
    assert (release / "compose.production.yaml").is_file()
    assert (release / "compose.staging.yaml").is_file()
    assert (release / "pyproject.toml").is_file()
    assert (release / "uv.lock").is_file()
    assert not (release / "frontend").exists()
    assert not (release / ".env.production").exists()
    assert not (release / "tests").exists()
