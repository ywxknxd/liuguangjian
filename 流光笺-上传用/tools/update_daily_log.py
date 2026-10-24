"""
开发日志更新脚本

用法：
    python tools/update_daily_log.py

此脚本会在 dev-logs/ 目录下创建一个以当天日期命名的日志文件（如 2026-07-07.md），
如果该文件已存在则打开供编辑。
"""

import os
import subprocess
import sys
from datetime import date


def main():
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dev-logs")
    os.makedirs(logs_dir, exist_ok=True)

    today = date.today().isoformat()
    log_path = os.path.join(logs_dir, f"{today}.md")

    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# {today} 开发日志\n\n")
            f.write("## 已完成\n- \n\n")
            f.write("## 待办事项\n- \n\n")
            f.write("## 备注\n- \n")

    # 尝试用默认编辑器打开
    if sys.platform == "win32":
        os.startfile(log_path)
    elif sys.platform == "darwin":
        subprocess.run(["open", log_path])
    else:
        subprocess.run(["xdg-open", log_path])

    print(f"日志文件已打开: {log_path}")


if __name__ == "__main__":
    main()
