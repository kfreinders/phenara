from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

from phenopi.config import SOURCE_ROOT, load_settings


def test_settings_default_to_the_cloned_repository():
    settings = load_settings({})

    assert settings.project_root == SOURCE_ROOT
    assert settings.runtime_dir == SOURCE_ROOT / "runtime"
    assert settings.capture_dir == SOURCE_ROOT / "captures"
    assert settings.venv_dir == SOURCE_ROOT / ".venv"
    assert settings.capture_script == (
        SOURCE_ROOT / "scripts" / "capture" / "capture_once.py"
    )
    assert settings.development_image_dir == (
        SOURCE_ROOT / "development" / "sample-images"
    )
    assert settings.python_bin == Path(sys.executable).absolute()


def test_settings_use_one_environment_for_gui_and_scheduler_paths(tmp_path):
    root = tmp_path / "installed phenopi"
    settings = load_settings({
        "PHENOPI_ROOT": str(root),
        "PHENOPI_RUNTIME_DIR": str(tmp_path / "state"),
        "PHENOPI_CAPTURE_DIR": str(tmp_path / "data"),
        "PHENOPI_DEVELOPMENT_IMAGE_DIR": str(tmp_path / "samples"),
        "PHENOPI_VENV_DIR": str(tmp_path / "python"),
        "PHENOPI_PYTHON": str(tmp_path / "python" / "bin" / "python"),
        "PHENOPI_TIMEZONE": "UTC",
        "PHENOPI_GUI_HOST": "127.0.0.1",
        "PHENOPI_GUI_PORT": "8080",
    })

    assert settings.project_root == root
    assert settings.schedule_path == tmp_path / "state" / "schedule.json"
    assert settings.capture_dir == tmp_path / "data"
    assert settings.development_image_dir == tmp_path / "samples"
    assert settings.timezone == ZoneInfo("UTC")
    assert settings.gui_host == "127.0.0.1"
    assert settings.gui_port == 8080


def test_configured_virtualenv_python_symlink_is_not_dereferenced(tmp_path):
    interpreter = tmp_path / "base-python"
    interpreter.write_text("")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(interpreter)

    settings = load_settings({"PHENOPI_PYTHON": str(venv_python)})

    assert settings.python_bin == venv_python
    assert settings.python_bin != interpreter


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_settings_reject_invalid_gui_port(port):
    with pytest.raises(ValueError, match="PHENOPI_GUI_PORT"):
        load_settings({"PHENOPI_GUI_PORT": port})


def test_installer_generates_both_services_for_the_current_checkout():
    installer = (SOURCE_ROOT / "deploy" / "install.sh").read_text()
    scheduler = (
        SOURCE_ROOT / "deploy/systemd/phenopi-scheduler.service.in"
    ).read_text()
    gui = (SOURCE_ROOT / "deploy/systemd/phenopi-gui.service.in").read_text()

    assert 'PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"' in installer
    assert 'INSTALL_USER="${USER:-$(id -un)}"' in installer
    assert "python3 -m venv --system-site-packages" in installer
    assert '"$PIP_BIN" install -r' in installer
    assert 'npm --prefix "$PROJECT_ROOT/gui/frontend" run build' in installer
    assert "systemctl enable phenopi-scheduler.service phenopi-gui.service" in installer
    assert "PHENOPI_DEVELOPMENT_IMAGE_DIR" in installer
    assert "EnvironmentFile=/etc/phenopi/phenopi.env" in scheduler
    assert "EnvironmentFile=/etc/phenopi/phenopi.env" in gui
    assert "-m scripts.scheduling.scheduler" in scheduler
    assert "-m gui.app" in gui
