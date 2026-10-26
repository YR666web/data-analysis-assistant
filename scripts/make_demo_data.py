"""Create a reproducible weekly sales workbook for a five-minute demonstration."""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


def main() -> None:
    monday = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    monday -= timedelta(days=monday.weekday())
    sunday = monday + timedelta(days=6)
    rows = [
        (monday, "阿莫西林", "抗生素", 2, 5, 10),
        (monday + timedelta(days=1), "布洛芬", "非抗生素", 2, 10, 20),
        (monday + timedelta(days=2), "阿莫西林", "抗生素", 3, 10, 30),
        (monday + timedelta(days=3), "布洛芬", "非抗生素", 4, 10, 40),
        (monday + timedelta(days=4), "阿莫西林", "抗生素", 5, 10, 50),
        (monday + timedelta(days=5), "布洛芬", "非抗生素", 6, 10, 60),
        (sunday + timedelta(days=1), "布洛芬", "非抗生素", 1, 999, 999),
    ]
    frame = pd.DataFrame(rows, columns=["销售日期", "药品", "分类", "数量", "单价", "销售额"])
    output = Path(__file__).resolve().parent.parent / "demo" / "weekly_sales_demo.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output) as book:
        frame.to_excel(book, sheet_name="销售明细", index=False)
        pd.DataFrame({"说明": ["演示数据，不是真实业务记录", "本周金额应为 210；下一周 999 不计入"]}).to_excel(
            book, sheet_name="说明", index=False)
    print(f"文件：{output}")
    print(f"演示问题：根据上传的 Excel 文件『销售明细』工作表，生成 {monday} 至 {sunday} 的销售周报。"
          "按药品汇总销售额，并写明匹配记录数、数据日期范围和下周记录是否排除。")
    print("人工核对：本周 6 笔，总额 210；阿莫西林 90，布洛芬 120。下一周的 999 不计入。")


if __name__ == "__main__":
    main()
