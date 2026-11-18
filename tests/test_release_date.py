"""验证实际升版配置能够写入、更新发布日期，并支持 dry-run。"""

import runpy
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest
import yaml
from bumpversion.bump import do_bump
from bumpversion.config import get_configuration

from plum_tools import _version, conf


@pytest.mark.parametrize("previous_date", ["", "2020-01-02"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_bump_patch_updates_version_and_release_date_in_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, previous_date: str, dry_run: bool
) -> None:
    project = Path(__file__).resolve().parents[1]
    config_path = tmp_path / "pyproject.toml"
    config_path.write_text((project / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = get_configuration(
        config_path, commit=False, tag=False, setup_hooks=[], pre_commit_hooks=[], post_commit_hooks=[]
    )
    conf_path = tmp_path / "src" / "plum_tools" / "_version.py"
    conf_path.parent.mkdir(parents=True)
    conf_path.write_text(f'VERSION = "{config.current_version}"\nRELEASE_DATE = "{previous_date}"\n', encoding="utf-8")
    answers_path = tmp_path / ".copier-answers.yml"
    answers_path.write_text(f"version: {config.current_version}\n", encoding="utf-8")
    before = {path: path.read_text(encoding="utf-8") for path in (config_path, conf_path, answers_path)}
    current = config.version_config.parse(config.current_version)
    next_version = config.version_config.serialize(current.bump("patch"), {})

    with mock.patch("bumpversion.context.datetime") as clock:
        clock.datetime.now.return_value = datetime(2030, 1, 2, 12, 34, 56)
        do_bump("patch", None, config, config_file=config_path, dry_run=dry_run)

    if dry_run:
        assert {path: path.read_text(encoding="utf-8") for path in before} == before
    else:
        assert conf_path.read_text(encoding="utf-8") == (f'VERSION = "{next_version}"\nRELEASE_DATE = "2030-01-02"\n')
        assert f'current_version = "{next_version}"' in config_path.read_text(encoding="utf-8")
        assert answers_path.read_text(encoding="utf-8") == f"version: {next_version}\n"


def test_conf_reexports_the_independent_version_metadata() -> None:
    assert conf.VERSION == _version.VERSION
    assert conf.RELEASE_DATE == _version.RELEASE_DATE


@pytest.mark.parametrize("commit_fields", ['COMMIT_ID = ""\n', 'COMMIT_ID = "old"\n', "", 'COMMIT_ID = ""\n' * 2])
def test_release_workflow_injects_commit_before_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_fields: str
) -> None:
    project = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((project / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build"]["steps"]
    metadata_step = next(step for step in steps if step.get("id") == "build_metadata")
    build_step = next(step for step in steps if step.get("run") == "uv build")
    assert steps.index(metadata_step) < steps.index(build_step)
    script = metadata_step["run"].split("<<'PY'\n", maxsplit=1)[1].rsplit("\nPY", maxsplit=1)[0]
    script_path = tmp_path / "stamp.py"
    script_path.write_text(script, encoding="utf-8")
    version_path = tmp_path / "src" / "plum_tools" / "_version.py"
    version_path.parent.mkdir(parents=True)
    source = 'VERSION = "1.2.3"\nRELEASE_DATE = "2030-01-02"\n' + commit_fields
    version_path.write_text(source, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    commit_id = "0123456789abcdef0123456789abcdef01234567"

    with mock.patch("subprocess.check_output", return_value=f"{commit_id}\n") as git:
        if commit_fields.count("COMMIT_ID") == 1:
            runpy.run_path(str(script_path), run_name="__main__")
            assert version_path.read_text(encoding="utf-8") == (
                'VERSION = "1.2.3"\nRELEASE_DATE = "2030-01-02"\n' + f'COMMIT_ID = "{commit_id}"\n'
            )
        else:
            with pytest.raises(SystemExit, match="唯一的 COMMIT_ID"):
                runpy.run_path(str(script_path), run_name="__main__")
            assert version_path.read_text(encoding="utf-8") == source
    git.assert_called_once_with(["git", "rev-parse", "HEAD"], text=True)
