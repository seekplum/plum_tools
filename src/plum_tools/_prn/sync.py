"""生成并执行 rsync 同步命令。"""

import os
import shlex
import subprocess

from plum_tools._prn.paths import (
    get_directory_path,
    is_directory_target,
    process_path,
    process_paths,
    process_remote_paths,
)
from plum_tools.utils.cli import call_process
from plum_tools.utils.constants import LOCAL_HOST
from plum_tools.utils.exceptions import RunCmdError
from plum_tools.utils.printer import print_error, print_ok, print_text, print_warn
from plum_tools.utils.sshconf import merge_ssh_config
from plum_tools.utils.utils import run_cmd


class SyncFiles:  # pylint: disable=too-many-instance-attributes
    """上传文件到服务器"""

    # pylint: disable=too-many-positional-arguments,too-many-arguments,too-many-locals
    def __init__(
        self,
        hostname: str,
        user: str,
        port: int,
        identityfile: str,
        src: str,
        dest: str,
        exclude: list[str] | None,
        delete: int,
        is_download: bool = False,
        is_debug: bool = False,
        ignore_rsync_path: bool = False,
        ignore_exclude: bool = False,
        include: list[str] | None = None,
        cli_exclude: list[str] | None = None,
        dry_run: bool = False,
        directory_root: str = "",
    ):
        """文件上传功能

        :param hostname 主机ip
        :example hostname 10.10.100.1

        :param user ssh登陆使用的用户名
        :example user 10.10.100.1

        :param port ssh登陆使用的端口号
        :example port 22

        :param identityfile 私钥文件路径
        :example identityfile ~/.ssh/id_rsa

        :param src 本地路径
        :example src /tmp

        :param dest 远程机器路径
        :example dest /tmp

        :param exclude 需要过滤的目录
        :example exclude [".git"]

        :param delete 是否删除远程机器目录下非本次上传的文件
        :example delete 0 0|1  0: 不删除 1: 删除

        :param is_download 是否是下载文件，默认是上传
        :example is_download False

        :param is_debug 是否打印详细信息
        :example is_debug False

        :param ignore_rsync_path 是否忽略 rsync-path 参数
        :example ignore_rsync_path False

        :param ignore_exclude 是否忽略 exclude 参数
        :example ignore_exclude False

        :param include 包含的目录
        :example include ["pkg"]

        :param cli_exclude 命令行传入的排除目录，--ignore-exclude 时仅保留此项
        :example cli_exclude ["node_modules"]
        """
        self._hostname = hostname
        self._user = user
        self._port = port
        self._identity_file = identityfile
        self._src = src
        self._dest = dest
        self._exclude = exclude or []
        self._include = set(include or [])
        self._cli_exclude = cli_exclude or []
        self._delete = delete
        self._is_download = is_download
        self._is_debug = is_debug
        self._dry_run = dry_run
        self._ignore_rsync_path = ignore_rsync_path
        self._ignore_exclude = ignore_exclude
        self._is_localhost = hostname == LOCAL_HOST
        self._directory_root = directory_root

    @property
    def host_info(self) -> str:
        """主机信息"""
        if self._is_localhost:
            return "本地机器"
        return f"{self._user}@{self._hostname} 服务器(端口: {self._port})"

    @property
    def user_prefix(self) -> str:
        """用户前缀"""
        if self._is_localhost:
            return ""
        return f"{self._user}@{self._hostname}:"

    def _get_sync_option(self) -> str:
        """组合出同步文件的命令"""
        option = ["rsync -rtlv"]
        known_host = "UserKnownHostsFile=/dev/null"
        host_key = "StrictHostKeyChecking no"
        timeout = "ConnectTimeout=10"
        # 指定端口
        if self._port:
            ssh_cmd = f"ssh -p {self._port}"
        else:
            ssh_cmd = "ssh"
        if not self._ignore_rsync_path and not self._is_download and not self._is_localhost:
            directory = os.path.dirname(self._dest)
            if not directory:
                directory = self._dest
            option.append(f"'--rsync-path=mkdir -p {directory} && rsync'")
        if not self._is_localhost:
            option.append(f'-e \'{ssh_cmd} -i {self._identity_file} -o "{known_host}" -o "{host_key}" -o "{timeout}"\'')
        if self._delete:
            option.append("--delete")
        exclude_items = self._cli_exclude if self._ignore_exclude else self._exclude
        exists = set()
        for item in exclude_items:
            if item in self._include or item in exists:
                continue
            exists.add(item)
            option.append(f"--exclude '{item}'")
        return " ".join(option)

    def _translate_directory(self) -> None:
        """同步目录目标，按实际来源处理缺项并保留目录内容复制语义。"""
        local = self._src if isinstance(self._src, list) else [self._src]
        remote = self._dest if isinstance(self._dest, list) else [self._dest]
        local_paths = [os.path.abspath(os.path.expanduser(path)) for path in local]
        try:
            root_paths = [get_directory_path(self._directory_root, path) for path in remote]
        except ValueError as exc:
            print_error(str(exc))
            raise SystemExit(1) from exc
        sources, destinations = (root_paths, local_paths) if self._is_download else (local_paths, root_paths)
        if len(destinations) != 1:
            print_error("目录模式只能指定一个目标路径")
            raise SystemExit(1)
        existing = []
        for path in sources:
            if not os.path.lexists(path):
                print_warn(f"源文件或目录不存在：{path}，跳过")
                continue
            existing.append(shlex.quote(process_path(path, is_local=True)))
        if not existing:
            return
        destination = destinations[0]
        if not self._dry_run:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
        src, dest = " ".join(existing), shlex.quote(destination)
        self._run_sync_command(src, dest, f"同步 {src} 到 {dest} ")

    def translate(self) -> None:
        """文件上传功能"""
        if self._directory_root:
            self._translate_directory()
            return
        # pv = "|pv -lep -s 117 >/dev/null"
        pv = ""

        if self._is_download:
            self._src, self._dest = process_remote_paths(self._dest, self.user_prefix, pv), process_paths(self._src)
        else:
            self._src, self._dest = process_paths(self._src, is_local=True), process_paths(self._dest)

        # 从远端下载文件到本地
        if self._is_download:
            src = self._src
            dest = self._dest
            text = f"从 {self.host_info} 下载 {self._src} 到本地 {self._dest} "
        # 从本地上传文件到远端
        else:
            src = self._src
            dest = f"{self.user_prefix}{self._dest}{pv}"
            text = f"上传 {self._src} 到 {self.host_info} {self._dest} "

        self._run_sync_command(src, dest, text)

    def _run_sync_command(self, src: str, dest: str, text: str) -> None:
        """统一预览或执行同步命令，保留调试输出和中断处理。"""
        rsync = self._get_sync_option()
        cmd = f"{rsync} {src} {dest}"
        if self._dry_run:
            print_text(cmd)
            return
        try:
            if self._is_debug:
                print_text(cmd)
                exit_code = call_process(subprocess.call, cmd, shell=True)  # nosec B604
                if exit_code != 0:
                    print_error(f"{text}失败, 错误码: {exit_code}")
                    return
            else:
                run_cmd(cmd)
            print_ok(f"{text}成功")
        except RunCmdError as e:
            print_error(f"{text}失败, 失败原因: {e.err_msg}")


def sync_files(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    host_list: list[str],
    host_type: str,
    user: str,
    port: int,
    identity_file: str,
    projects_conf: list[dict],
    is_download: bool = False,
    is_debug: bool = False,
    ignore_rsync_path: bool = False,
    ignore_exclude: bool = False,
    exclude: list[str] | None = None,
    include: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """上传文件到服务器上

    :param host_list 服务器列表
    :example host_list [1, 2]

    :param host_type 主机类型
    :example host_type 1

    :param user ssh登陆用户名
    :example user root

    :param port ssh登陆端口
    :example port 22

    :param user ssh登陆用户名
    :example user root

    :param identity_file ssh登陆私钥文件路径
    :example identity_file ~/.ssh/id_rsa

    :param projects_conf 需要上传的项目配置列表
    :example pro_conf [{
        "src": "/tmp",
        "dest": "/tmp",
        "exclude": [".git"],
        "delete": 0
    }]

    :param is_download 是否是下载文件，默认是上传
    :example is_download False

    :param is_debug 是否打印详细信息
    :example is_debug False

    :param ignore_rsync_path 是否忽略 rsync-path 参数
    :example ignore_rsync_path False

    :param ignore_exclude 是否忽略 exclude 参数
    :example ignore_exclude False

    :param exclude 命令行传入的排除目录，--ignore-exclude 时仅保留此项
    :example exclude ["node_modules"]

    :param include 包含的目录
    :example include ["pkg"]
    """
    for host in host_list:
        directory_root = os.path.abspath(os.path.expanduser(host)) if is_directory_target(host) else ""
        if host == LOCAL_HOST or directory_root:
            ssh_conf = {"hostname": LOCAL_HOST, "user": "", "port": 0, "identityfile": ""}
            if directory_root:
                ssh_conf["directory_root"] = directory_root
        else:
            ssh_conf = merge_ssh_config(host, host_type, user, port, identity_file)
        ssh_conf.update(
            {
                "is_download": is_download,
                "is_debug": is_debug,
                "ignore_rsync_path": ignore_rsync_path,
                "ignore_exclude": ignore_exclude,
                "cli_exclude": exclude,
                "include": include,
                "dry_run": dry_run,
            }
        )
        for pro_conf in projects_conf:
            sync = SyncFiles(**{**pro_conf, **ssh_conf})
            sync.translate()
