"""汇总本机技能、MCP 和规则的可观察使用记录。"""

from plum_tools._agent_usage.cli import main as report_main
from plum_tools.utils.cli import cli_entry


@cli_entry
def main() -> int:
    """生成所选客户端的本机使用报告。"""
    return report_main()


if __name__ == "__main__":
    raise SystemExit(main())
