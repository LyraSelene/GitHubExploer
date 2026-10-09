from __future__ import annotations

import argparse
import ctypes
import json
import queue
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from core import APP_NAME, Cancelled, DEFAULT_LEARNING_TRACK, Model, PROFILE_FIELDS, Store, Transport, UserError, import_material, research
from learning import GitHubLearning

BG = "#f4f6fa"
CARD = "#ffffff"
INK = "#172338"
MUTED = "#64748b"
BLUE = "#345de3"
SIDEBAR = "#172238"
FONT = "Microsoft YaHei UI"


def set_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App(GitHubLearning):
    def __init__(self, root, store=None):
        self.root = root
        self.store = store or Store()
        self.profile = self.store.get("profile", {})
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.current = None
        self.accumulated = ""
        self.evidence = []
        self.report_id = None
        self.root.title(APP_NAME + " · AI Infra 项目研究员")
        self.root.geometry("1230x830")
        self.root.minsize(1040, 700)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", (FONT, 10))
        self.configure_style()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(80, self.poll)

    def configure_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=(FONT, 10))
        style.configure("TButton", padding=(14, 9), font=(FONT, 10), borderwidth=0,
                        background="#e8edf5", foreground=INK)
        style.map("TButton", background=[("active", "#dce4f3")], foreground=[("disabled", "#99a5b8")])
        style.configure("Primary.TButton", background=BLUE, foreground="white")
        style.map("Primary.TButton", background=[("active", "#2349c6"), ("disabled", "#bdc9f0")])
        style.configure("TEntry", padding=8, fieldbackground=CARD, bordercolor="#dce3ee")
        style.configure("TCombobox", padding=8, fieldbackground=CARD)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), background="#e8edf5")
        style.map("TNotebook.Tab", background=[("selected", CARD)])
        style.configure("TCheckbutton", background=BG, foreground=INK)

    def label(self, parent, text, size=10, color=INK, bg=BG, **kwargs):
        return tk.Label(parent, text=text, font=(FONT, size), fg=color, bg=bg, **kwargs)

    def build(self):
        sidebar = tk.Frame(self.root, bg=SIDEBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.label(sidebar, "INFRA / LAB", 10, "#92a9db", SIDEBAR, anchor="w").pack(fill="x", padx=24, pady=(28, 8))
        self.label(sidebar, "Infra 研究室", 20, "white", SIDEBAR, anchor="w").pack(fill="x", padx=22)
        self.label(sidebar, "从读懂项目，到验证机制", 10, "#acbad2", SIDEBAR, anchor="w").pack(fill="x", padx=24, pady=(9, 26))
        for text, action in [("＋  新建研究", self.new), ("⌘  GitHub 学习", self.github_learning), ("◷  研究历史", self.history), ("◎  我的背景", self.profile_dialog), ("⚙  模型连接", self.settings_dialog)]:
            tk.Button(sidebar, text=text, command=action, anchor="w", bg=SIDEBAR,
                      fg="#e2e9f5", activebackground="#293955", activeforeground="white",
                      relief="flat", bd=0, padx=23, pady=13, cursor="hand2").pack(fill="x", padx=10, pady=2)
        bottom = tk.Frame(sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=24, pady=24)
        self.label(bottom, "你的工程学习顾问", 11, "#d4def1", SIDEBAR, anchor="w").pack(fill="x")
        self.label(bottom, "源码证据 · 设计取舍\n最小实践 · 本地历史", 9, "#91a2bf", SIDEBAR,
                   justify="left", anchor="w").pack(fill="x", pady=(9, 0))

        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True, padx=26, pady=22)
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 15))
        self.label(header, "把别人的项目，变成你的能力", 22, anchor="w").pack(side="left")
        self.connection_label = self.label(header, "未配置模型", 9, MUTED)
        self.connection_label.pack(side="right", padx=4)

        input_card = tk.Frame(main, bg=CARD, highlightbackground="#e1e7f0", highlightthickness=1)
        input_card.pack(fill="x")
        self.label(input_card, "01  /  提交研究材料", 11, INK, CARD, anchor="w").pack(fill="x", padx=18, pady=(14, 7))
        self.url = tk.StringVar()
        url_row = tk.Frame(input_card, bg=CARD)
        url_row.pack(fill="x", padx=18)
        self.url_entry = ttk.Entry(url_row, textvariable=self.url)
        self.url_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(url_row, text="导入文件", command=self.import_file).pack(side="right", padx=(8, 0))
        self.label(input_card, "GitHub 仓库首页 / 文章链接，或在下方粘贴 README、源码、论文文本", 9, MUTED, CARD,
                   anchor="w").pack(fill="x", padx=18, pady=(7, 5))
        self.material = ScrolledText(input_card, height=4, wrap="word", relief="flat", bd=0,
                                     bg="#f7f9fc", fg=INK, font=(FONT, 10), padx=10, pady=8,
                                     highlightthickness=1, highlightbackground="#e6ebf3")
        self.material.pack(fill="x", padx=18)
        self.agent_focus = tk.BooleanVar(value=self.store.get("agent_focus", True))
        focus_row = tk.Frame(input_card, bg=CARD)
        focus_row.pack(fill="x", padx=18, pady=(8, 0))
        ttk.Checkbutton(focus_row, text="补充 AI Agent 学习价值与作者构建路径", variable=self.agent_focus,
                        command=lambda: self.store.set("agent_focus", self.agent_focus.get())).pack(side="left")
        action_row = tk.Frame(input_card, bg=CARD)
        action_row.pack(fill="x", padx=18, pady=12)
        self.profile_summary = self.label(action_row, "个人背景未填写 · 可先分析材料", 9, MUTED, CARD, anchor="w")
        self.profile_summary.pack(side="left")
        self.start_button = ttk.Button(action_row, text="开始研究  →", style="Primary.TButton", command=self.start)
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(action_row, text="停止", command=self.stop, state="disabled")
        self.cancel_button.pack(side="right", padx=8)

        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, pady=(18, 0))
        report_frame = tk.Frame(self.notebook, bg=CARD)
        evidence_frame = tk.Frame(self.notebook, bg=CARD)
        self.notebook.add(report_frame, text="研究报告")
        self.notebook.add(evidence_frame, text="阅读证据")
        toolbar = tk.Frame(report_frame, bg=CARD)
        toolbar.pack(fill="x", padx=15, pady=8)
        self.label(toolbar, "02  /  价值判断 → 核心机制 → 最小实践", 10, MUTED, CARD).pack(side="left")
        ttk.Button(toolbar, text="导出 Markdown", command=self.export).pack(side="right")
        ttk.Button(toolbar, text="复制", command=self.copy).pack(side="right", padx=6)
        self.agent_button = ttk.Button(toolbar, text="Agent 学习 / 作者路径", command=self.analyze_agent)
        self.agent_button.pack(side="right", padx=6)
        self.report_text = ScrolledText(report_frame, wrap="word", relief="flat", bd=0, bg=CARD, fg=INK,
                                       font=(FONT, 11), padx=20, pady=12, spacing1=4, spacing3=7)
        self.report_text.pack(fill="both", expand=True)
        self.report_text.tag_configure("h1", font=(FONT, 19, "bold"), foreground=INK, spacing1=12, spacing3=10)
        self.report_text.tag_configure("h2", font=(FONT, 15, "bold"), foreground=INK, spacing1=12, spacing3=8)
        self.report_text.tag_configure("h3", font=(FONT, 12, "bold"), foreground=BLUE, spacing1=8)
        self.report_text.tag_configure("bold", font=(FONT, 11, "bold"))
        self.report_text.tag_configure("code", font=("Consolas", 10), background="#f0f3f9")
        self.report_text.tag_configure("table", font=("Consolas", 10), background="#f7f9fc")
        self.report_text.tag_configure("link", foreground=BLUE, underline=True)

        self.label(evidence_frame, "仅列出实际取得的材料。文件目录不代表已读源码。", 10, MUTED, CARD,
                   anchor="w").pack(fill="x", padx=20, pady=(17, 8))
        self.evidence_list = tk.Listbox(evidence_frame, bg=CARD, fg=INK, relief="flat", bd=0,
                                       font=(FONT, 11), selectbackground="#e3eaff", selectforeground=INK)
        self.evidence_list.pack(fill="both", expand=True, padx=20)
        evidence_actions = tk.Frame(evidence_frame, bg=CARD)
        evidence_actions.pack(fill="x", padx=20, pady=12)
        ttk.Button(evidence_actions, text="查看已读片段", command=self.inspect_evidence).pack(side="left")
        ttk.Button(evidence_actions, text="打开来源", command=self.open_evidence).pack(side="left", padx=8)
        follow_row = tk.Frame(main, bg=BG)
        follow_row.pack(fill="x", pady=(13, 0))
        self.followup = tk.StringVar()
        self.follow_entry = ttk.Entry(follow_row, textvariable=self.followup)
        self.follow_entry.pack(side="left", fill="x", expand=True)
        self.follow_entry.bind("<Return>", lambda event: self.ask())
        self.ask_button = ttk.Button(follow_row, text="继续追问", command=self.ask)
        self.ask_button.pack(side="right", padx=(8, 0))
        self.status = tk.StringVar(value="就绪 · 填写模型连接后即可开始；报告与背景保存在本机。")
        self.label(main, "", 9, MUTED, anchor="w", textvariable=self.status).pack(fill="x", pady=(10, 0))
        self.refresh_summary()
        self.welcome()

    def welcome(self):
        self.render("# 先判断值不值得学，再决定怎么做\n\n提交一个项目，让研究员帮你找到最值得投入的 1–3 个机制。\n\n"
                    "### 你将得到\n投入结论与适用阶段；真实请求的执行路径；源码证据与设计取舍；一个可以独立完成的最小练习。\n"
                    "默认还分析 AI Agent 有什么值得学，以及作者有记录的构建过程；实际记录与推荐实现路线会分开说明。\n\n"
                    "### 从这里开始\n1. 打开「模型连接」，填写接口地址、模型名与密钥。\n"
                    "2. 可在「我的背景」填写基础、硬件和目标。\n"
                    "3. 输入仓库首页链接，或粘贴 / 导入材料，然后点击「开始研究」。\n\n"
                    "也可以打开「GitHub 学习」，搜索主题、选择仓库，生成源码阅读路线与练习清单，并记录学习进度。\n\n"
                    "阅读源码与运行实验会明确区分。当前应用读取材料，不执行仓库代码。")

    def render(self, text):
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        in_code = False
        for line in text.splitlines():
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.report_text.insert("end", line + "\n", "code")
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                self.report_text.insert("end", heading[2] + "\n", "h" + str(min(len(heading[1]), 3)))
                continue
            if line.strip().startswith("|"):
                if not re.fullmatch(r"[|\s:\-]+", line):
                    self.report_text.insert("end", line + "\n", "table")
                continue
            line = re.sub(r"^\s*[-*]\s+", "  •  ", line)
            parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?://[^\s)]+\))", line)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    self.report_text.insert("end", part[2:-2], "bold")
                elif part.startswith("`") and part.endswith("`"):
                    self.report_text.insert("end", part[1:-1], "code")
                elif re.match(r"\[.+\]\(https?://", part):
                    match = re.fullmatch(r"\[(.+)\]\((.+)\)", part)
                    tag = "url_" + str(self.report_text.index("end"))
                    self.report_text.insert("end", match[1], ("link", tag))
                    self.report_text.tag_bind(tag, "<Button-1>", lambda event, url=match[2]: self.browser(url))
                else:
                    self.report_text.insert("end", part)
            self.report_text.insert("end", "\n")
        self.report_text.configure(state="disabled")

    def refresh_summary(self):
        settings = self.store.settings()
        self.connection_label.configure(text=settings.get("model") or "未配置模型")
        values = [self.profile.get(k, "").strip() for k in ["兴趣方向", "近期目标", "可用硬件"]]
        summary = " / ".join(v for v in values if v)
        self.profile_summary.configure(text=summary[:55] if summary else "个人背景未填写 · 可先分析材料")

    def idle_required(self):
        if self.busy:
            self.status.set("研究正在进行，请先停止或等待完成。")
            return False
        return True

    def new(self):
        if not self.idle_required():
            return
        self.current = None
        self.report_id = None
        self.accumulated = ""
        self.evidence = []
        self.evidence_list.delete(0, "end")
        self.url.set("")
        self.material.delete("1.0", "end")
        self.followup.set("")
        self.welcome()
        self.notebook.select(0)
        self.status.set("新研究 · 输入项目链接或材料。")

    def import_file(self):
        if not self.idle_required():
            return
        filename = filedialog.askopenfilename(title="导入研究材料", filetypes=[("研究材料", "*.md *.txt *.pdf *.py *.cpp *.cu *.rs *.json *.yaml *.toml"), ("所有文件", "*.*")])
        if not filename:
            return
        try:
            text = import_material(Path(filename))
            self.material.delete("1.0", "end")
            self.material.insert("1.0", text)
            self.status.set("已导入 " + Path(filename).name)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc) if isinstance(exc, UserError) else "无法读取该文件。")

    def start(self):
        if not self.idle_required():
            return
        url = self.url.get().strip()
        material = self.material.get("1.0", "end-1c")
        if not url and not material.strip():
            messagebox.showinfo("添加材料", "请输入项目链接，或粘贴 / 导入材料。")
            return
        self.current = None
        self.report_id = None
        self.evidence = []
        self.evidence_list.delete(0, "end")
        self.accumulated = ""
        self.run(url, material, "", None)

    def ask(self):
        if not self.idle_required():
            return
        question = self.followup.get().strip()
        if not question:
            self.status.set("在输入框中填写想继续研究的问题。")
            return
        if not self.current:
            messagebox.showinfo("先完成研究", "先生成或打开一份报告，再继续追问。")
            return
        self.followup.set("")
        track = self.current["context"].get("learning_track")
        focus = track.startswith("AI Agent") if track else None
        self.run("", "", question, self.current["context"], agent_focus=focus)

    def analyze_agent(self):
        if not self.idle_required():
            return
        if not self.current:
            self.agent_focus.set(True)
            self.store.set("agent_focus", True)
            self.status.set("已启用专项分析，提交材料后点击开始研究。")
            return
        self.run("", "", "请补充分析：这个项目对学习 AI Agent 有哪些值得借鉴的地方，以及作者是怎么制作出来的？", self.current["context"], agent_focus=True)

    def run(self, url, material, question, previous, agent_focus=None, learning_goal=None, learning_track=DEFAULT_LEARNING_TRACK):
        settings = self.store.settings()
        if not settings.get("model"):
            self.settings_dialog()
            return
        self.busy = True
        self.cancel = threading.Event()
        self.start_button.configure(state="disabled")
        self.ask_button.configure(state="disabled")
        self.agent_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.notebook.select(0)
        self.render("# 正在研究\n\n先收集材料，再分析最值得学习的核心机制。实际阅读的文件会出现在「阅读证据」中。")
        self.status.set("开始读取材料…")
        prior_report = self.accumulated
        title = (url.rstrip("/").split("/")[-1] if url else material.strip().splitlines()[0])[:80] if not previous else self.current["title"]
        profile = dict(self.profile)
        focus = self.agent_focus.get() if agent_focus is None else agent_focus
        report_id = self.report_id

        def worker():
            try:
                result = research(settings, profile, url, material, question, self.cancel,
                                  lambda kind, value: self.events.put((kind, value)), previous, agent_focus=focus,
                                  learning=learning_goal is not None, learning_track=learning_track)
                if self.cancel.is_set():
                    raise Cancelled()
                complete_report = prior_report + "\n\n---\n\n## 追问\n" + question + "\n\n" + result["report"] if previous else result["report"]
                result.update(report=complete_report, title=title or "材料研究")
                result["id"] = self.store.save_report(result["title"], complete_report, result["context"], result["evidence"], report_id)
                if learning_goal is not None:
                    repo = result["context"]["sources"].get("repo")
                    if result.get("learning_tasks") and repo:
                        result["learning_id"] = self.store.save_learning(result["id"], repo, learning_goal, result["learning_tasks"], learning_track)
                self.events.put(("done", result))
            except Cancelled:
                self.events.put(("cancelled", prior_report))
            except Exception as exc:
                message = str(exc) if isinstance(exc, UserError) else "研究未完成。可能是服务响应格式或材料格式不兼容，请检查模型配置，或减少材料后重试。"
                self.events.put(("error", (message, prior_report)))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        needs_render = False
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.set(value)
                elif kind == "turn":
                    self.stream_text = ""
                    self.render("正在生成分析…")
                elif kind == "token":
                    self.stream_text = getattr(self, "stream_text", "") + value
                    needs_render = True
                elif kind == "evidence":
                    self.evidence.append(value)
                    self.add_evidence(value)
                elif kind == "done":
                    needs_render = False
                    self.current = value
                    self.report_id = value["id"]
                    self.accumulated = value["report"]
                    self.evidence = value["evidence"]
                    self.render(self.accumulated)
                    self.finish()
                    self.status.set("研究完成 · 已保存到本机，可导出报告或继续追问。")
                    if value.get("learning_id"):
                        self.status.set("学习计划已保存 · 打开“GitHub 学习 → 我的学习进度”查看任务并记录结果。")
                    elif value.get("learning_warning"):
                        self.status.set(value["learning_warning"])
                elif kind in {"error", "cancelled"}:
                    needs_render = False
                    prior_report = value[1] if kind == "error" else value
                    self.render(prior_report or ("# 研究已停止\n未完成的输出没有保存为正式报告。" if kind == "cancelled" else "# 研究未完成\n" + value[0]))
                    if self.current:
                        self.evidence = list(self.current["evidence"])
                        self.evidence_list.delete(0, "end")
                        for item in self.evidence:
                            self.add_evidence(item)
                    self.finish()
                    self.status.set("已停止 · 可以修改材料后重试。" if kind == "cancelled" else "研究未完成 · " + value[0])
                    if kind == "error":
                        messagebox.showerror("研究未完成", value[0])
        except queue.Empty:
            pass
        if needs_render:
            self.render(self.stream_text)
            self.report_text.see("end")
        self.root.after(120, self.poll)

    def finish(self):
        self.busy = False
        self.start_button.configure(state="normal")
        self.ask_button.configure(state="normal")
        self.agent_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def stop(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("正在停止 · 等待当前网络读取结束，通常几秒，最长约 45 秒。")

    def add_evidence(self, item):
        span = f"  L{item['start']}–L{item['end']}" if item.get("start") else ""
        self.evidence_list.insert("end", "  " + item["path"] + span)

    def selected_evidence(self):
        selection = self.evidence_list.curselection()
        return self.evidence[selection[0]] if selection else None

    def inspect_evidence(self):
        item = self.selected_evidence()
        if not item:
            self.status.set("先选择一个已读文件或材料。")
            return
        window = self.dialog("已读片段 · " + item["path"], "850x620")
        self.label(window, item["url"] or "用户导入材料", 9, MUTED, wraplength=780, anchor="w").pack(fill="x", padx=20, pady=15)
        text = ScrolledText(window, font=("Consolas", 10), wrap="word", bg=CARD, relief="flat", padx=12, pady=12)
        text.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        text.insert("1.0", item.get("excerpt") or "取得了仓库文件目录；未读取目录中所有文件的内容。")
        text.configure(state="disabled")

    def browser(self, url):
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)

    def open_evidence(self):
        item = self.selected_evidence()
        if item and item.get("url"):
            self.browser(item["url"])

    def copy(self):
        if not self.accumulated:
            self.status.set("完成研究后可以复制报告。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.accumulated)
        self.status.set("报告已复制。")

    def export(self):
        if not self.accumulated:
            self.status.set("完成研究后可以导出报告。")
            return
        title = re.sub(r'[<>:"/\\|?*]', "_", self.current["title"]) if self.current else "研究报告"
        filename = filedialog.asksaveasfilename(title="导出研究报告", initialfile=title + ".md", defaultextension=".md", filetypes=[("Markdown", "*.md")])
        if filename:
            evidence = "\n\n## 实际阅读材料\n\n" + "\n".join("- " + item["path"] + (" — " + item["url"] if item["url"] else "") for item in self.evidence)
            try:
                Path(filename).write_text(self.accumulated + evidence, encoding="utf-8")
                self.status.set("已导出：" + filename)
            except OSError:
                messagebox.showerror("导出失败", "无法写入所选文件，请选择其他位置。")

    def dialog(self, title, geometry):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry(geometry)
        window.configure(bg=BG)
        window.transient(self.root)
        window.grab_set()
        return window

    def profile_dialog(self):
        if not self.idle_required():
            return
        window = self.dialog("我的学习背景", "650x690")
        self.label(window, "让建议适合你当前的阶段", 18, anchor="w").pack(fill="x", padx=25, pady=(20, 6))
        self.label(window, "只填相关内容即可。留空表示未知，不表示没有基础或设备。", 9, MUTED,
                   anchor="w").pack(fill="x", padx=25, pady=(0, 15))
        placeholders = ["语言、系统、网络、分布式或深度学习基础", "一个代表性项目与自己负责的部分", "推理服务 / 训练 / 性能 / 数据 / 算力调度 / 未定", "CPU、内存、GPU 型号与显存", "例如每周 6 小时", "建立基础 / 实践 / 求职 / 具体工程问题"]
        entries = {}
        for field, hint in zip(PROFILE_FIELDS, placeholders):
            self.label(window, field + "  ·  " + hint, 9, MUTED, anchor="w").pack(fill="x", padx=25, pady=(8, 5))
            variable = tk.StringVar(value=self.profile.get(field, ""))
            ttk.Entry(window, textvariable=variable).pack(fill="x", padx=25)
            entries[field] = variable

        def save():
            self.profile = {key: value.get().strip() for key, value in entries.items()}
            self.store.set("profile", self.profile)
            self.refresh_summary()
            window.destroy()
            self.status.set("个人背景已保存。新研究会使用这份背景。")

        ttk.Button(window, text="保存背景", command=save, style="Primary.TButton").pack(anchor="e", padx=25, pady=20)

    def settings_dialog(self):
        if not self.idle_required():
            return
        window = self.dialog("模型连接", "700x620")
        settings = self.store.settings()
        self.label(window, "连接你的模型服务", 18, anchor="w").pack(fill="x", padx=26, pady=(22, 8))
        self.label(window, "使用 OpenAI 兼容的 Chat Completions 接口。密钥保存在本机，以 Windows 用户身份加密。", 9, MUTED,
                   anchor="w", wraplength=630, justify="left").pack(fill="x", padx=26, pady=(0, 12))
        variables = {key: tk.StringVar(value=settings.get(key, "")) for key in ["base_url", "model", "api_key"]}
        for key, title in [("base_url", "接口地址（Base URL，通常以 /v1 结尾）"), ("model", "模型名称（填写服务商提供的准确名称）"), ("api_key", "API Key（本机服务可留空）")]:
            self.label(window, title, 10, anchor="w").pack(fill="x", padx=26, pady=(12, 6))
            if key == "base_url":
                field = ttk.Combobox(window, textvariable=variables[key], values=["https://api.openai.com/v1", "https://api.deepseek.com/v1", "http://127.0.0.1:11434/v1"])
            else:
                field = ttk.Entry(window, textvariable=variables[key], show="•" if key == "api_key" else "")
            field.pack(fill="x", padx=26)
        tools = tk.BooleanVar(value=settings.get("source_tools", True))
        ttk.Checkbutton(window, text="允许模型按需读取仓库源码（模型需支持工具调用）", variable=tools).pack(anchor="w", padx=26, pady=(18, 5))
        self.label(window, "关闭时只分析已自动读取的 README 或导入材料，报告会注明限制。\n项目材料和个人背景会发送到你选择的模型服务。测试连接也会产生一次模型请求。", 9, MUTED,
                   justify="left", anchor="w", wraplength=630).pack(fill="x", padx=26, pady=(2, 12))
        connection_status = tk.StringVar(value="填好连接信息后可以测试。")
        self.label(window, "", 9, MUTED, anchor="w", wraplength=630, textvariable=connection_status).pack(fill="x", padx=26)
        row = tk.Frame(window, bg=BG)
        row.pack(fill="x", padx=26, pady=18)

        def values():
            return {**{key: variable.get().strip() for key, variable in variables.items()}, "source_tools": tools.get()}

        def save():
            try:
                self.store.save_settings(values())
                self.refresh_summary()
                window.destroy()
                self.status.set("模型连接已保存。现在可以开始研究。")
            except UserError as exc:
                messagebox.showerror("配置未保存", str(exc), parent=window)

        def test():
            configuration = values()
            connection_status.set("连接测试中…")
            test_button.configure(state="disabled")
            results = queue.Queue()

            def worker():
                transport = Transport(threading.Event())
                try:
                    model = Model(configuration, transport)
                    model.complete([{"role": "user", "content": "请只回复：连接成功"}], [], lambda text: None)
                    results.put("连接成功。可保存配置；源码工具支持情况需要在研究时验证。")
                except Exception as exc:
                    results.put(str(exc) if isinstance(exc, UserError) else "服务响应不兼容，请核对接口地址和模型名称。")
                finally:
                    transport.close()

            def check():
                if not window.winfo_exists():
                    return
                try:
                    connection_status.set(results.get_nowait())
                    test_button.configure(state="normal")
                except queue.Empty:
                    window.after(150, check)

            threading.Thread(target=worker, daemon=True).start()
            window.after(150, check)

        test_button = ttk.Button(row, text="测试连接", command=test)
        test_button.pack(side="left")
        ttk.Button(row, text="保存连接", style="Primary.TButton", command=save).pack(side="right")

    def history(self):
        if not self.idle_required():
            return
        window = self.dialog("研究历史", "750x560")
        self.label(window, "你的项目研究记录", 18, anchor="w").pack(fill="x", padx=24, pady=(22, 12))
        rows = self.store.reports()
        listing = tk.Listbox(window, bg=CARD, fg=INK, font=(FONT, 11), relief="flat", bd=0,
                             selectbackground="#e3eaff", selectforeground=INK)
        listing.pack(fill="both", expand=True, padx=24)
        for _, title, date in rows:
            listing.insert("end", "  " + date + "   " + title)
        if not rows:
            listing.insert("end", "  还没有报告。完成第一次研究后会自动保存在这里。")

        def open_report(event=None):
            selection = listing.curselection()
            if not selection or not rows:
                return
            item = self.store.report(rows[selection[0]][0])
            self.current = item
            self.report_id = item["id"]
            self.accumulated = item["report"]
            self.evidence = item["evidence"]
            self.evidence_list.delete(0, "end")
            for evidence in self.evidence:
                self.add_evidence(evidence)
            self.render(self.accumulated)
            self.notebook.select(0)
            self.status.set("已打开历史报告：" + item["title"])
            window.destroy()

        listing.bind("<Double-Button-1>", open_report)
        ttk.Button(window, text="打开报告", command=open_report, style="Primary.TButton").pack(anchor="e", padx=24, pady=18)

    def close(self):
        if self.busy and not messagebox.askyesno("退出研究室", "研究还在进行。退出会停止研究，未完成的结果不会保存。"):
            return
        self.cancel.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    set_dpi()
    root = tk.Tk()
    app = App(root, Store(args.data_dir) if args.data_dir else None)
    if args.preview:
        root.update()
        coordinates = [root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()]
        (app.store.directory / "preview-window.json").write_text(json.dumps(coordinates), encoding="utf-8")
        root.after(20000, root.destroy)
    if args.smoke_test:
        root.update()
        app.agent_focus.set(False)
        app.analyze_agent()
        assert app.agent_focus.get()
        app.render("# 界面检查\n**证据**与 `函数`\n[来源](https://github.com/openai/openai-python)\n|能力|练习|\n|---|---|\n|队列|取消|\n```python\nprint(42)\n```")
        root.update()
        app.profile_dialog()
        root.update()
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        app.settings_dialog()
        root.update()
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        app.history()
        root.update()
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        app.github_learning()
        root.update()
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        if not app.store.learning_projects():
            fixture_report = app.store.save_report("UI test repository", "# 学习报告\n测试夹具", {"sources": {}}, [])
            app.store.save_learning(fixture_report, {"owner": "fixture", "name": "repo", "commit": "test-commit"}, "界面检查", [
                {"title": "追踪状态", "reading": "main.py（测试夹具）", "question": "状态在哪一步变化？",
                 "exercise": "绘制状态图", "acceptance": "给出正常与异常两条路径"}])
        app.github_learning()
        root.update()
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        root.destroy()
        (app.store.directory / "smoke-test-passed.txt").write_text("Desktop UI smoke test passed.", encoding="utf-8")
        print("Desktop UI smoke test passed.")
        return
    root.mainloop()


if __name__ == "__main__":
    main()
