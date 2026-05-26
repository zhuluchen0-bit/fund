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


CURL_PATH = "/usr/bin/curl"


def fetch_top10_holdings(fund_code):
    """从天天基金获取基金最新十大重仓股（使用 curl 绕过 SSL 兼容问题）"""
    url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10&year=&month=&rt=0.1"
    try:
        result = sp.run([
            CURL_PATH, "-s", "-A",
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
    """从腾讯行情获取实时股价（使用 curl 避免 SSL 兼容问题）"""
    if stock_code.startswith("6"):
        sec = f"sh{stock_code}"
    else:
        sec = f"sz{stock_code}"

    url = f"https://qt.gtimg.cn/q={sec}"
    result = sp.run([CURL_PATH, "-s", url], capture_output=True, timeout=10)
    if result.returncode != 0:
        raise Exception(f"curl 行情请求失败 {stock_code}")
    data = result.stdout.decode("gbk", errors="replace")

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

        # 自定义配色
        self.COLORS = {
            "bg": "#f5f6fa",
            "header_bg": "#1a1a2e",
            "header_fg": "#ffffff",
            "toolbar_bg": "#e8e9ef",
            "table_bg": "#ffffff",
            "table_alt": "#f8f9ff",
            "table_header_bg": "#eef0f8",
            "green": "#00b894",
            "red": "#e17055",
            "add": "#00b894",
            "delete": "#e17055",
            "refresh": "#0984e3",
            "edit": "#fdcb6e",
            "btn_fg": "#ffffff",
            "btn_font": ("PingFang SC", 12, "bold"),
            "text": "#2d3436",
            "subtext": "#b2bec3",
        }

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                       background=self.COLORS["table_bg"],
                       foreground=self.COLORS["text"],
                       fieldbackground=self.COLORS["table_bg"],
                       font=("PingFang SC", 12),
                       rowheight=32,
                       borderwidth=0)
        style.configure("Treeview.Heading",
                       background=self.COLORS["table_header_bg"],
                       foreground=self.COLORS["text"],
                       font=("PingFang SC", 11, "bold"),
                       borderwidth=1,
                       relief="flat")
        style.map("Treeview",
                  background=[("selected", "#dfe6e9")],
                  foreground=[("selected", self.COLORS["text"])])

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

    def make_btn(self, parent, text, cmd, bg, padx=16):
        """统一风格的按钮"""
        btn = tk.Label(parent, text=text, cursor="hand2",
                      bg=bg, fg=self.COLORS["btn_fg"],
                      font=self.COLORS["btn_font"],
                      padx=padx, pady=6)
        btn.pack(side="left", padx=4, pady=6)
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.config(bg=self._lighten(bg)))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _lighten(self, color):
        """颜色变亮 15%"""
        c = color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r = min(255, int(r + (255 - r) * 0.3))
        g = min(255, int(g + (255 - g) * 0.3))
        b = min(255, int(b + (255 - b) * 0.3))
        return f"#{r:02x}{g:02x}{b:02x}"

    def create_widgets(self):
        root_bg = self.COLORS["bg"]
        self.root.configure(bg=root_bg)

        # 顶部标题栏
        title_frame = tk.Frame(self.root, bg=self.COLORS["header_bg"], height=56)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="\U0001F4CA  基金净值估算", font=("PingFang SC", 20, "bold"),
                fg=self.COLORS["header_fg"], bg=self.COLORS["header_bg"]).pack(side="left", padx=24, pady=12)
        tk.Label(title_frame, text="天天基金 / 腾讯行情", font=("PingFang SC", 11),
                fg="#636e72", bg=self.COLORS["header_bg"]).pack(side="right", padx=24)

        # 工具栏
        toolbar = tk.Frame(self.root, bg=self.COLORS["toolbar_bg"], height=44)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        self.make_btn(toolbar, "   + 添加基金  ", self.add_fund_dialog, self.COLORS["add"], padx=18)
        self.make_btn(toolbar, "   \u2702 删除  ", self.delete_selected, self.COLORS["delete"], padx=18)
        self.make_btn(toolbar, "   \U0001F504 刷新  ", self.refresh_all, self.COLORS["refresh"], padx=18)
        self.make_btn(toolbar, "   \u270F 编辑  ", self.edit_selected, self.COLORS["edit"], padx=18)

        # 状态栏
        tk.Frame(toolbar, bg=self.COLORS["toolbar_bg"], width=20).pack(side="left")
        self.status_indicator = tk.Canvas(toolbar, width=10, height=10,
                                          bg=self.COLORS["toolbar_bg"],
                                          highlightthickness=0)
        self.status_indicator.pack(side="right", padx=(0, 4))
        self._dot = self.status_indicator.create_oval(0, 0, 10, 10,
                                                      fill=self.COLORS["green"],
                                                      outline="")
        self.status_label = tk.Label(toolbar, text="就绪", font=("PingFang SC", 11),
                                     fg=self.COLORS["subtext"], bg=self.COLORS["toolbar_bg"])
        self.status_label.pack(side="right", padx=(0, 18))

        # 主区域
        main_frame = tk.Frame(self.root, bg=self.COLORS["bg"])
        main_frame.pack(fill="both", expand=True, padx=10, pady=(8, 4))

        # 表格
        columns = ("基金代码", "基金名称", "持仓金额", "持有份额", "持仓收益率",
                   "当日涨跌", "当日收益", "更新后收益率", "覆盖率", "状态")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings",
                                height=15, selectmode="browse")

        col_widths = [90, 210, 120, 110, 110, 95, 120, 120, 80, 80]
        for col, w in zip(columns, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")

        self.tree.column("基金名称", anchor="w")
        self.tree.column("持仓金额", anchor="e")
        self.tree.column("持有份额", anchor="e")
        self.tree.column("当日收益", anchor="e")

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y", padx=(4, 0))

        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        # 底部栏
        footer = tk.Frame(self.root, bg=self.COLORS["toolbar_bg"], height=36)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        tk.Label(footer,
                text="\u2139\ufe0f 双击基金编辑  |  点击「刷新」获取实时行情  |  每15秒自动更新",
                font=("PingFang SC", 10), fg=self.COLORS["subtext"],
                bg=self.COLORS["toolbar_bg"]).pack(side="left", padx=20)

        self.auto_refresh()

    def auto_refresh(self):
        """每15秒自动刷新一次已获取数据的基金"""
        self.refresh_prices()
        self.root.after(15000, self.auto_refresh)

    def set_status(self, text, is_ok=True):
        self.status_label.config(text=text)
        color = self.COLORS["green"] if is_ok else self.COLORS["red"]
        try:
            self.status_indicator.itemconfig(self._dot, fill=color)
        except:
            pass
        self.root.update_idletasks()

    def _make_dialog(self, title, fields, defaults, callback, extra_row=None):
        """统一对话框样式"""
        bg = self.COLORS["bg"]
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("460x360")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=bg)

        # 标题头
        tk.Frame(dialog, bg=self.COLORS["header_bg"], height=40).pack(fill="x")

        # 表单
        form = tk.Frame(dialog, bg=bg, padx=30, pady=20)
        form.pack(fill="both", expand=True)

        entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(form, text=label, font=("PingFang SC", 11),
                    fg=self.COLORS["text"], bg=bg).grid(row=i, column=0, padx=(0, 15), pady=7, sticky="w")
            entry = tk.Entry(form, font=("PingFang SC", 12),
                           bd=1, relief="solid", highlightthickness=0)
            entry.grid(row=i, column=1, padx=0, pady=7, sticky="ew", ipady=3)
            default = defaults.get(key, "")
            if default:
                entry.insert(0, str(default))
            entries[key] = entry

        form.columnconfigure(1, weight=1)

        # 额外行
        extra_row_index = len(fields)
        if extra_row:
            extra_row(form, entries, extra_row_index)

        # 按钮
        btn_frame = tk.Frame(form, bg=bg)
        btn_frame.grid(row=extra_row_index + 1, column=0, columnspan=2, pady=(15, 0))

        def ok():
            result = {}
            for _, key in fields:
                val = entries[key].get().strip()
                result[key] = val if val else None
            callback(result, dialog)

        def cancel():
            dialog.destroy()

        # 取消按钮
        tk.Label(btn_frame, text="    取消    ", cursor="hand2",
                bg=self.COLORS["toolbar_bg"], fg=self.COLORS["text"],
                font=self.COLORS["btn_font"], padx=18, pady=6).pack(side="left", padx=6)
        btn_cancel = btn_frame.winfo_children()[-1]
        btn_cancel.bind("<Button-1>", lambda e: cancel())
        btn_cancel.bind("<Enter>", lambda e: btn_cancel.config(bg=self.COLORS["subtext"]))
        btn_cancel.bind("<Leave>", lambda e: btn_cancel.config(bg=self.COLORS["toolbar_bg"]))

        # 确认按钮
        tk.Label(btn_frame, text="    确认    ", cursor="hand2",
                bg=self.COLORS["refresh"], fg="#ffffff",
                font=self.COLORS["btn_font"], padx=18, pady=6).pack(side="left", padx=6)
        btn_ok = btn_frame.winfo_children()[-1]
        btn_ok.bind("<Button-1>", lambda e: ok())
        btn_ok.bind("<Enter>", lambda e: btn_ok.config(bg=self._lighten(self.COLORS["refresh"])))
        btn_ok.bind("<Leave>", lambda e: btn_ok.config(bg=self.COLORS["refresh"]))

        dialog.bind("<Return>", lambda e: ok())
        return dialog

    def add_fund_dialog(self):
        fields = [
            ("基金代码", "code"),
            ("基金名称（选填）", "name"),
            ("持仓金额（元）", "amount"),
            ("持有份额", "shares"),
            ("当前收益率（%）", "yield_pct"),
        ]

        def extra(form, entries, row):
            def fetch():
                code = entries["code"].get().strip()
                if not code:
                    return
                try:
                    n, _, _ = fetch_top10_holdings(code)
                    entries["name"].delete(0, "end")
                    entries["name"].insert(0, n)
                except:
                    pass
            lbl = tk.Label(form, text="  \U0001F50D 自动获取名称  ", cursor="hand2",
                          bg=self.COLORS["edit"], fg=self.COLORS["text"],
                          font=("PingFang SC", 10), padx=10, pady=4)
            lbl.grid(row=row, column=1, sticky="w", pady=(4, 0))
            lbl.bind("<Button-1>", lambda e: fetch())
            lbl.bind("<Enter>", lambda e: lbl.config(bg=self._lighten(self.COLORS["edit"])))
            lbl.bind("<Leave>", lambda e: lbl.config(bg=self.COLORS["edit"]))

        def callback(result, dialog):
            code = result.get("code")
            if not code:
                messagebox.showwarning("提示", "基金代码不能为空")
                return
            item = {
                "code": code,
                "name": result.get("name") or f"基金{code}",
                "amount": float(result["amount"]) if result.get("amount") else 0,
                "shares": float(result["shares"]) if result.get("shares") else 0,
                "yield_pct": float(result["yield_pct"]) if result.get("yield_pct") else 0,
            }
            self.portfolio.append(item)
            self.save_portfolio()
            self.refresh_display()
            dialog.destroy()

        self._make_dialog("添加基金", fields, {}, callback, extra)

    def edit_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中要编辑的基金")
            return

        idx = self.tree.index(selection[0])
        item = self.portfolio[idx]

        fields = [
            ("基金代码", "code"),
            ("基金名称", "name"),
            ("持仓金额（元）", "amount"),
            ("持有份额", "shares"),
            ("当前收益率（%）", "yield_pct"),
        ]

        defaults = {
            "code": item.get("code", ""),
            "name": item.get("name", ""),
            "amount": str(item.get("amount", 0)),
            "shares": str(item.get("shares", 0)),
            "yield_pct": str(item.get("yield_pct", 0)),
        }

        def callback(result, dialog):
            self.portfolio[idx] = {
                "code": result["code"] or item["code"],
                "name": result.get("name") or item.get("name", ""),
                "amount": float(result["amount"]) if result.get("amount") else 0,
                "shares": float(result["shares"]) if result.get("shares") else 0,
                "yield_pct": float(result["yield_pct"]) if result.get("yield_pct") else 0,
            }
            self.save_portfolio()
            self.refresh_display()
            dialog.destroy()

        self._make_dialog(f"编辑基金 - {item['code']}", fields, defaults, callback)

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

        alt = False
        for item in self.portfolio:
            prev_yield = item.get("yield_pct", 0)
            amount = item.get("amount", 0)
            est_chg = item.get("_est_chg", None)
            coverage = item.get("_coverage", None)

            if est_chg is not None:
                daily_pnl = amount * est_chg / 100.0
                new_yield = 100 * ((1 + prev_yield / 100) * (1 + est_chg / 100) - 1)
                chg_text = f"{est_chg:+.2f}%"
                pnl_text = f"{daily_pnl:+,.0f}"
                yield_text = f"{new_yield:+.2f}%"
                cov_text = f"{coverage*100:.1f}%" if coverage else "-"
                status = "\u2705"  # 已更新
            else:
                chg_text = "-"
                pnl_text = "-"
                yield_text = f"{prev_yield:+.2f}%"
                cov_text = "-"
                status = "\u23F3"  # 待刷新

            values = (
                item["code"],
                item.get("name", f"基金{item['code']}"),
                f"{amount:,.0f}",
                f"{item.get('shares', 0):,.2f}",
                f"{prev_yield:+.2f}%",
                chg_text,
                f"{pnl_text}",
                yield_text,
                cov_text,
                status,
            )
            tag = "even" if alt else "odd"
            chg_tag = "gain" if (est_chg is not None and est_chg >= 0) else ""
            loss_tag = "loss" if (est_chg is not None and est_chg < 0) else ""
            self.tree.insert("", "end", values=values, tags=(tag, chg_tag, loss_tag))
            alt = not alt

        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("odd", background="#f8f9ff")
        self.tree.tag_configure("gain", foreground=self.COLORS["green"])
        self.tree.tag_configure("loss", foreground=self.COLORS["red"])

    def refresh_all(self):
        """全部基金重新获取数据"""
        self.set_status("正在获取数据...", True)
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
                self.root.after(0, lambda: self.set_status(f"正在获取 {code} ...", True))
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
                self.root.after(0, lambda: self.set_status(f"{code}: {e}", False))

        self.save_portfolio()
        self.root.after(0, self.refresh_display)
        self.root.after(0, lambda: self.set_status(f"更新完成 ({len(self.portfolio)} 只基金)", True))
        self.root.after(0, self.refresh_button_state, True)

    def refresh_button_state(self, enabled):
        for child in self.root.winfo_children():
            for label in child.winfo_children():
                if isinstance(label, tk.Label):
                    try:
                        label.config(state="normal" if enabled else "disabled")
                    except:
                        pass


def main():
    root = tk.Tk()
    app = FundPortfolioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
