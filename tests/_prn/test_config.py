"""验证 config 的相关行为。"""

from unittest import mock

import pytest

from plum_tools._prn.config import get_project_conf
from plum_tools.utils.constants import PathConfig
from plum_tools.utils.exceptions import RunCmdError, SystemTypeError


@pytest.mark.parametrize(
    "project, src, dest, delete, exclude",
    [
        ("plum", "/tmp", "/tmp", 0, []),
        ("plum", "/tmp", "/tmp", 0, [".git"]),
        ("2", "/tmp", "/tmp", 1, [".git"]),
        ("1", "/tmp/1", "/tmp/2", 1, [".git", "*.pyc"]),
        ("1", "/tmp/1", "/tmp/2", None, [".git", "*.pyc"]),
        ("xxx", "/tmp/1", "/tmp/2", None, []),
    ],
)
def test_get_project_conf(project: str, src: str, dest: str, delete: int | None, exclude: list[str]) -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={
                "projects": {
                    project: {
                        "src": "/tmp",
                        "dest": "/tmp",
                        "delete": None,
                        "exclude": [],
                    }
                }
            },
        ) as p,
        mock.patch("plum_tools._prn.config.get_file_abspath", side_effect=lambda x: x),
    ):
        data = get_project_conf(project, [src], [dest], delete, exclude)
        assert data == {
            "exclude": exclude,
            "delete": delete,
            "src": [src],
            "dest": [dest],
        }
        p.assert_called_with(PathConfig.PLUM_YML_PATH)


def test_get_project_conf_does_not_mutate_yaml_project_config() -> None:
    yml_data = {"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}}

    with (
        mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value=yml_data),
        mock.patch("plum_tools._prn.config.get_file_abspath", side_effect=lambda value: f"abs:{value}"),
    ):
        data = get_project_conf("demo", [], [], None, [])

    assert data == {"src": ["abs:/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}
    assert yml_data == {"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}}


def test_get_project_conf_uses_yaml_defaults_and_normalizes_to_lists() -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ) as mock_parse,
        mock.patch(
            "plum_tools._prn.config.get_file_abspath", side_effect=lambda value: f"abs:{value}"
        ) as mock_get_file_abspath,
    ):
        data = get_project_conf("demo", [], [], None, [])

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    mock_get_file_abspath.assert_called_once_with("/tmp/src")
    assert data == {"src": ["abs:/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}


def test_get_project_conf_skips_abspath_for_download() -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ),
        mock.patch("plum_tools._prn.config.get_file_abspath") as mock_get_file_abspath,
    ):
        data = get_project_conf("demo", [], [], None, [], True)

    mock_get_file_abspath.assert_not_called()
    assert data == {"src": ["/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}


def test_get_project_conf_exits_when_project_missing_without_paths() -> None:
    with (
        mock.patch("plum_tools.utils.utils.YmlConfig.parse_config_yml", return_value={"projects": {}}),
        mock.patch("plum_tools._prn.config.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            get_project_conf("missing", [], [], None, [])

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with(f"yml文件: {PathConfig.PLUM_YML_PATH} 中没有配置项目: missing 的信息")


@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        (RunCmdError("fail", "", "stderr"), "/tmp/src 文件/目录不存在"),
        (SystemTypeError("unsupported"), "unsupported"),
    ],
)
def test_get_project_conf_exits_when_local_path_resolution_fails(side_effect: Exception, message: str) -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ),
        mock.patch("plum_tools._prn.config.get_file_abspath", side_effect=side_effect),
        mock.patch("plum_tools._prn.config.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            get_project_conf("demo", [], [], None, [])

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with(message)


def test_get_project_conf_skips_abspath_when_resolve_src_false() -> None:
    with (
        mock.patch(
            "plum_tools.utils.utils.YmlConfig.parse_config_yml",
            return_value={"projects": {"demo": {"src": "/tmp/src", "dest": "/tmp/dest"}}},
        ),
        mock.patch("plum_tools._prn.config.get_file_abspath") as mock_get_file_abspath,
    ):
        data = get_project_conf("demo", [], [], None, [], is_download=False, resolve_src=False)

    mock_get_file_abspath.assert_not_called()
    assert data == {"src": ["/tmp/src"], "dest": ["/tmp/dest"], "exclude": [], "delete": 0}
