#!/usr/bin/env python3
"""
基金净值估算工具 - 本地桌面版
管理基金持仓，根据十大重仓股实时行情估算当日净值涨跌
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import subprocess as sp
import threading
import re
from datetime import datetime, timezone, timedelta

# ========== 配置 ==========
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fund_portfolio.json")
CNY_TZ = timezone(timedelta(hours=8))


def fetch_top10_holdings(fund_code):
    """从天天基金获取基金最新十大重仓股（使用 curl 绕过 SSL 兼容问题）"""
    url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10&year=&month=&rt=0.1"
    try:
        result = sp.run([
            "curl", "-s", "-A",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            url
        ], capture_output=True, timeout=30)
        if result.returncode != 0:
            raise Exception(f"curl 失败")
        data = result.stdout.decode("utf-8")
    except sp.TimeoutExpired:
        raise Exception("获取持仓超时")
    except Exception as e:
        raise Exception(f"获取持仓失败: {e}")

    # 从 JavaScript 变量中提取 HTML 内容
    m = re.search(r'content:"(.*?)",\s*arryear', data, re.DOTALL)
    if not m:
        raise Exception("无法解析基金持仓数据")
    content = m.group(1).replace("\\n", "\n")

    # 解析基金名称
    name_m = re.search(r"title='([^']+)'", content)
    name = name_m.group(1) if name_m else f"基金{fund_code}"

    # 解析表格行: <tr>...<td>序号</td><td><a...>股票代码</a></td>...<td class='tor'>比例%</td>
    rows = re.findall(
        r'<tr>.*?<td>\d+</td>.*?<a[^>]*>(\d{6})</a>.*?<td[^>]*>([\d.]+)%</td>',
        content, re.DOTALL
    )

    codes = []
    weights = []
    seen = set()
    for code, pct in rows:
        if code not in seen and len(codes) < 10:
            seen.add(code)
            codes.append(code)
            weights.append(float(pct))

    if len(codes) < 3:
        raise Exception(f"未能解析足够的重仓股数据（仅识别到 {len(codes)} 只）")

    return name, codes, weights


def get_stock_quote(stock_code):
    """从腾讯行情获取实时股价"""
    if stock_code.startswith("6"):
        sec = f"sh{stock_code}"
    else:
        sec = f"sz{stock_code}"

    url = f"https://qt.gtimg.cn/q={sec}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("gbk")

    fields = data.split("~")
    if len(fields) < 33:
        raise Exception(f"行情数据格式异常: {stock_code}")

    price = float(fields[3])
    chg_pct = float(fields[32])
    return price, chg_pct


def estimate_fund_return(fund_code):
    """估算基金当日涨跌幅，返回 (基金名称, 股票列表, 预估涨跌幅%, 覆盖率%)"""
    name, codes, weights = fetch_top10_holdings(fund_code)
    total_weight = sum(weights)
    weighted_sum = 0.0
    stock_data = []

    for code, w in zip(codes, weights):
        try:
            price, chg = get_stock_quote(code)
            contrib = chg * w / 100.0
            weighted_sum += contrib
            stock_data.append((code, price, chg, w, contrib))
        except Exception as e:
            stock_data.append((code, None, None, w, None))

    estimated = weighted_sum  # 百分比格式
    coverage = total_weight / 100.0
    return name, stock_data, estimated, coverage


class FundPortfolioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("基金净值估算工具")
        self.root.geometry("1100x680")
        self.root.minsize(900, 500)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("Helvetica", 12), rowheight=30)
        style.configure("Treeview.Heading", font=("Helvetica", 12, "bold"))

        self.portfolio = self.load_portfolio()
        self.create_widgets()
        self.refresh_display()

    def load_portfolio(self):
        """从本地文件加载持仓数据"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return []
        return []

    def save_portfolio(self):
        """保存持仓数据到本地"""
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.portfolio, f, ensure_ascii=False, indent=2)

    def create_widgets(self):
        # 顶部标题栏
        title_frame = tk.Frame(self.root, bg="#2b5797", height=50)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="基金净值估算工具", font=("Helvetica", 18, "bold"),
                 fg="white", bg="#2b5797").pack(side="left", padx=20, pady=10)
        tk.Label(title_frame, text="数据来源：天天基金 + 腾讯行情",
                 font=("Helvetica", 10), fg="#ccd5e0", bg="#2b5797").pack(side="right", padx=20)

        # 工具栏
        toolbar = tk.Frame(self.root, bg="#f0f0f0", height=40)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text="+ 添加基金", command=self.add_fund_dialog,
                  bg="#4CAF50", fg="white", font=("Helvetica", 11), padx=12).pack(side="left", padx=10, pady=5)
        tk.Button(toolbar, text="删除选中", command=self.delete_selected,
                  bg="#f44336", fg="white", font=("Helvetica", 11), padx=12).pack(side="left", padx=5, pady=5)
        tk.Button(toolbar, text="全部刷新", command=self.refresh_all,
                  bg="#2196F3", fg="white", font=("Helvetica", 11), padx=12).pack(side="left", padx=5, pady=5)
        tk.Button(toolbar, text="编辑选中", command=self.edit_selected,
                  bg="#FF9800", fg="white", font=("Helvetica", 11), padx=12).pack(side="left", padx=5, pady=5)

        self.status_label = tk.Label(toolbar, text="就绪", font=("Helvetica", 10),
                                     fg="#666", bg="#f0f0f0")
        self.status_label.pack(side="right", padx=15)

        # 主表格
        columns = ("基金代码", "基金名称", "持仓金额", "持有份额", "持仓收益率",
                   "当日涨跌", "当日收益", "更新后收益率", "覆盖率", "状态")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=15)

        col_widths = [90, 200, 110, 100, 100, 90, 110, 110, 80, 80]
        for col, w in zip(columns, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")

        self.tree.column("基金名称", anchor="w")
        self.tree.column("持仓金额", anchor="e")
        self.tree.column("持有份额", anchor="e")
        self.tree.column("当日收益", anchor="e")

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)

        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        # 底部说明栏
        footer = tk.Frame(self.root, bg="#f8f8f8", height=50)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(footer,
                 text="双击基金可编辑 | 点击「全部刷新」获取实时数据",
                 font=("Helvetica", 10), fg="#999", bg="#f8f8f8").pack(side="left", padx=20, pady=12)

        # 启动自动刷新
        self.auto_refresh()

    def auto_refresh(self):
        """每15秒自动刷新一次已获取数据的基金"""
        self.refresh_prices()
        self.root.after(15000, self.auto_refresh)

    def set_status(self, text):
        self.status_label.config(text=text)
        self.root.update_idletasks()

    def add_fund_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("添加基金")
        dialog.geometry("500x280")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        fields = [
            ("基金代码 *", "code"),
            ("持仓金额（元）", "amount"),
            ("持有份额", "shares"),
            ("当前持仓收益率（%）", "yield_pct"),
        ]

        entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(dialog, text=label, font=("Helvetica", 11)).grid(row=i, column=0, padx=15, pady=8, sticky="w")
            entry = tk.Entry(dialog, font=("Helvetica", 12), width=30)
            entry.grid(row=i, column=1, padx=10, pady=8)
            entries[key] = entry

        tk.Label(dialog, text="基金名称", font=("Helvetica", 11)).grid(row=4, column=0, padx=15, pady=8, sticky="w")
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, font=("Helvetica", 12), width=30, textvariable=name_var)
        name_entry.grid(row=4, column=1, padx=10, pady=8)

        def on_submit():
            code = entries["code"].get().strip()
            if not code:
                messagebox.showwarning("提示", "基金代码不能为空")
                return

            amount = entries["amount"].get().strip()
            shares = entries["shares"].get().strip()
            yield_pct = entries["yield_pct"].get().strip()

            item = {
                "code": code,
                "name": name_var.get().strip() or f"基金{code}",
                "amount": float(amount) if amount else 0,
                "shares": float(shares) if shares else 0,
                "yield_pct": float(yield_pct) if yield_pct else 0,
            }

            self.portfolio.append(item)
            self.save_portfolio()
            self.refresh_display()
            dialog.destroy()

        def on_fetch_name():
            code = entries["code"].get().strip()
            if not code:
                return
            try:
                tm_name, _, _ = fetch_top10_holdings(code)
                name_var.set(tm_name)
            except:
                pass

        btn_frame = tk.Frame(dialog)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=15)

        tk.Button(btn_frame, text="获取基金名称", command=on_fetch_name,
                  bg="#607D8B", fg="white", font=("Helvetica", 10), padx=8).pack(side="left", padx=5)
        tk.Button(btn_frame, text="确认添加", command=on_submit,
                  bg="#4CAF50", fg="white", font=("Helvetica", 11), padx=15).pack(side="left", padx=10)

        dialog.bind("<Return>", lambda e: on_submit())

    def edit_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中要编辑的基金")
            return

        idx = self.tree.index(selection[0])
        item = self.portfolio[idx]

        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑基金 - {item['code']}")
        dialog.geometry("500x320")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        fields = [
            ("基金代码", "code"),
            ("基金名称", "name"),
            ("持仓金额（元）", "amount"),
            ("持有份额", "shares"),
            ("当前持仓收益率（%）", "yield_pct"),
        ]

        entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(dialog, text=label, font=("Helvetica", 11)).grid(row=i, column=0, padx=15, pady=8, sticky="w")
            entry = tk.Entry(dialog, font=("Helvetica", 12), width=30)
            entry.insert(0, str(item.get(key, "")))
            entry.grid(row=i, column=1, padx=10, pady=8)
            entries[key] = entry

        def on_submit():
            self.portfolio[idx] = {
                "code": entries["code"].get().strip(),
                "name": entries["name"].get().strip(),
                "amount": float(entries["amount"].get()) if entries["amount"].get().strip() else 0,
                "shares": float(entries["shares"].get()) if entries["shares"].get().strip() else 0,
                "yield_pct": float(entries["yield_pct"].get()) if entries["yield_pct"].get().strip() else 0,
            }
            self.save_portfolio()
            self.refresh_display()
            dialog.destroy()

        tk.Button(dialog, text="保存修改", command=on_submit,
                  bg="#FF9800", fg="white", font=("Helvetica", 11), padx=15).grid(row=6, column=0, columnspan=2, pady=15)

        dialog.bind("<Return>", lambda e: on_submit())

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中要删除的基金")
            return

        if messagebox.askyesno("确认删除", "确定要删除选中的基金吗？"):
            indices = [self.tree.index(s) for s in selection]
            for idx in sorted(indices, reverse=True):
                self.portfolio.pop(idx)
            self.save_portfolio()
            self.refresh_display()

    def refresh_display(self):
        """刷新表格显示（不重新计算）"""
        for row in self.tree.get_children():
            self.tree.delete(row)

        for item in self.portfolio:
            prev_yield = item.get("yield_pct", 0)
            amount = item.get("amount", 0)
            est_chg = item.get("_est_chg", None)
            coverage = item.get("_coverage", None)

            if est_chg is not None:
                daily_pnl = amount * est_chg / 100.0
                new_yield = 100 * ((1 + prev_yield / 100) * (1 + est_chg / 100) - 1)
                chg_text = f"{est_chg:+.2f}%"
                pnl_text = f"{daily_pnl:+,.0f} 元"
                yield_text = f"{new_yield:+.2f}%"
                cov_text = f"{coverage*100:.1f}%" if coverage else "-"
                status = "已更新" if est_chg >= 0 else "已更新"
            else:
                chg_text = "-"
                pnl_text = "-"
                yield_text = f"{prev_yield:+.2f}%"
                cov_text = "-"
                status = "待刷新"

            values = (
                item["code"],
                item.get("name", f"基金{item['code']}"),
                f"{amount:,.0f}",
                f"{item.get('shares', 0):,.2f}",
                f"{prev_yield:+.2f}%",
                chg_text,
                pnl_text,
                yield_text,
                cov_text,
                status,
            )
            tag = "positive" if (est_chg is not None and est_chg >= 0) else "negative"
            self.tree.insert("", "end", values=values, tags=(tag,))

        self.tree.tag_configure("positive", foreground="green")
        self.tree.tag_configure("negative", foreground="red")

    def refresh_all(self):
        """全部基金重新获取数据"""
        self.set_status("正在获取数据...")
        self.refresh_button_state(False)
        threading.Thread(target=self._refresh_all_thread, daemon=True).start()

    def refresh_prices(self):
        """仅刷新已有缓存数据的基金的实时价格（轻量刷新）"""
        items_to_refresh = [i for i, item in enumerate(self.portfolio)
                            if item.get("_codes") and len(item["_codes"]) == 10]
        if not items_to_refresh:
            return

        changed = False
        for idx in items_to_refresh:
            item = self.portfolio[idx]
            try:
                codes = item["_codes"]
                weights = item["_weights"]
                total_weight = sum(weights)
                weighted_sum = 0.0

                for code, w in zip(codes, weights):
                    try:
                        _, chg = get_stock_quote(code)
                        weighted_sum += chg * w / 100.0
                    except:
                        pass

                item["_est_chg"] = weighted_sum
                item["_coverage"] = total_weight / 100.0
                changed = True
            except:
                pass

        if changed:
            self.root.after(0, self.refresh_display)

    def _refresh_all_thread(self):
        """后台线程：获取所有基金数据"""
        for idx in range(len(self.portfolio)):
            item = self.portfolio[idx]
            code = item["code"]
            try:
                self.root.after(0, self.set_status, f"正在获取 {code} ...")
                name, codes, weights = fetch_top10_holdings(code)
                item["name"] = name
                item["_codes"] = codes
                item["_weights"] = weights

                total_weight = sum(weights)
                weighted_sum = 0.0
                for sc, w in zip(codes, weights):
                    try:
                        _, chg = get_stock_quote(sc)
                        weighted_sum += chg * w / 100.0
                    except Exception as e:
                        pass

                item["_est_chg"] = weighted_sum
                item["_coverage"] = total_weight / 100.0

            except Exception as e:
                item.pop("_est_chg", None)
                item.pop("_coverage", None)
                self.root.after(0, self.set_status, f"{code}: {e}")

        self.save_portfolio()
        self.root.after(0, self.refresh_display)
        self.root.after(0, self.set_status, f"更新完成 ({len(self.portfolio)} 只基金)")
        self.root.after(0, self.refresh_button_state, True)

    def refresh_button_state(self, enabled):
        for child in self.root.winfo_children():
            for button in child.winfo_children():
                if isinstance(button, tk.Button):
                    try:
                        button.config(state="normal" if enabled else "disabled")
                    except:
                        pass


def main():
    root = tk.Tk()
    app = FundPortfolioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
