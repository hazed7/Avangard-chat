import importlib.util
from pathlib import Path


def _load_checker_module():
    checker_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / ("check_architecture_imports.py")
    )
    spec = importlib.util.spec_from_file_location("architecture_checker", checker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_architecture_checker_accepts_valid_boundaries(tmp_path: Path):
    checker = _load_checker_module()
    checker.PROJECT_ROOT = tmp_path
    checker.APP_ROOT = tmp_path / "app"

    _write(
        checker.APP_ROOT / "modules" / "messages" / "router.py",
        "from app.platform.config.settings import Settings\n",
    )
    _write(
        checker.APP_ROOT / "platform" / "security" / "tokens.py",
        "from app.platform.config.settings import Settings\n",
    )

    assert checker.main() == 0


def test_architecture_checker_rejects_legacy_import_paths(tmp_path: Path):
    checker = _load_checker_module()
    checker.PROJECT_ROOT = tmp_path
    checker.APP_ROOT = tmp_path / "app"

    _write(
        checker.APP_ROOT / "modules" / "messages" / "router.py",
        "from app.service.message_service import MessageService\n",
    )

    assert checker.main() == 1


def test_architecture_checker_rejects_platform_to_modules_imports(tmp_path: Path):
    checker = _load_checker_module()
    checker.PROJECT_ROOT = tmp_path
    checker.APP_ROOT = tmp_path / "app"

    _write(
        checker.APP_ROOT / "platform" / "http" / "deps.py",
        "from app.modules.auth.service import AuthService\n",
    )

    assert checker.main() == 1
