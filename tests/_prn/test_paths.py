"""验证 paths 的相关行为。"""

from unittest import mock

import pytest

from plum_tools._prn.paths import (
    get_directory_path,
    is_directory_target,
    process_path,
    process_paths,
    process_remote_paths,
)


def test_process_path_and_helpers() -> None:
    with mock.patch("plum_tools._prn.paths.os.path.isdir", side_effect=lambda path: path == "/tmp/dir"):
        assert process_path("/tmp/dir", is_local=True) == "/tmp/dir/"
        assert process_path("/tmp/file", is_local=True) == "/tmp/file"

    assert process_path("/remote/path/", is_local=False) == "/remote/path"
    assert process_paths(["/tmp/a", "/tmp/b/"], is_local=False) == "/tmp/a /tmp/b"
    assert process_paths("/tmp/a", is_local=True) == "/tmp/a"
    assert process_remote_paths(["/a/", "/b"], "user@host:", "") == "user@host:/a/ user@host:/b"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/abs/path", True),
        ("~/home", True),
        ("./rel", True),
        ("../rel", True),
        ("~", True),
        (".", True),
        ("..", True),
        ("dev", False),
        ("1.1.1.1", False),
        ("~user", False),
    ],
)
def test_is_directory_target(target: str, expected: bool) -> None:
    assert is_directory_target(target) is expected


@pytest.mark.parametrize(
    ("root", "path", "expected"),
    [
        ("/srv/app", "~", "/srv/app"),
        ("/srv/app", "~/python", "/srv/app/python"),
        ("/srv/app", "/srv/app/go", "/srv/app/srv/app/go"),
        ("/srv/app", "go", "/srv/app/go"),
        ("/srv/app", "python/go", "/srv/app/python/go"),
    ],
)
def test_get_directory_path_maps_paths(root: str, path: str, expected: str) -> None:
    assert get_directory_path(root, path) == expected


@pytest.mark.parametrize(
    ("root", "path", "message"),
    [
        ("/srv/app", "~user", "目录目标不支持其他用户的家目录"),
        ("/srv/app", "../../etc", "配置路径超出目录根路径"),
    ],
)
def test_get_directory_path_rejects_invalid_path(root: str, path: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        get_directory_path(root, path)
