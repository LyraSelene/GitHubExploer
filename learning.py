"""GitHub discovery and user-reported learning progress UI."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from pathlib import Path

from core import DEFAULT_LEARNING_TRACK, LEARNING_TRACKS, Transport, UserError, github_repo, search_github

BG, CARD, INK, MUTED, FONT = "#f4f6fa", "#ffffff", "#172338", "#64748b", "Microsoft YaHei UI"


class GitHubLearning:
    def github_learning(self):
        if not self.idle_required():
            return
        window = self.dialog("GitHub 学习 · AI Infra / AI Agent", "980x870")
        window.minsize(820, 700)
        self.label(window, "从一个仓库，练成一个机制", 20, anchor="w").pack(fill="x", padx=24, pady=(20, 7))
        self.label(window, "选择 AI Infra 或 AI Agent 方向，搜索项目、阅读源码、完成机制实验并复盘。", 10, MUTED,
                   anchor="w", wraplength=900).pack(fill="x", padx=24, pady=(0, 12))
        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        discover = tk.Frame(notebook, bg=BG)
        progress = tk.Frame(notebook, bg=BG)
        notebook.add(discover, text="找项目 / 开始学习")
        notebook.add(progress, text="我的学习进度")
        self._discovery_ui(window, discover)
        self._progress_ui(window, progress)

    def _discovery_ui(self, window, parent):
        saved_track = self.store.get("learning_track", DEFAULT_LEARNING_TRACK)
        if saved_track not in LEARNING_TRACKS:
            saved_track = DEFAULT_LEARNING_TRACK
        track = tk.StringVar(value=saved_track)
        track_row = tk.Frame(parent, bg=BG)
        track_row.pack(fill="x", pady=(12, 0))
        self.label(track_row, "学习方向", 10).pack(side="left", padx=(0, 10))
        track_choice = ttk.Combobox(track_row, textvariable=track, state="readonly", values=list(LEARNING_TRACKS), width=32)
        track_choice.pack(side="left")
        self.label(track_row, "关键词和目标可以自行修改", 9, MUTED).pack(side="left", padx=12)
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(15, 8))
        query = tk.StringVar(value=LEARNING_TRACKS[saved_track]["query"])
        ttk.Entry(row, textvariable=query).pack(side="left", fill="x", expand=True)
        language = tk.StringVar(value="不限语言")
        ttk.Combobox(row, textvariable=language, state="readonly", width=14,
                     values=["不限语言", "Python", "C++", "Rust", "Go", "TypeScript", "Java", "C"]).pack(side="left", padx=8)
        search_button = ttk.Button(row, text="搜索 GitHub")
        search_button.pack(side="right")
        status = tk.StringVar(value="搜索只读取 GitHub 公共信息，不调用模型。结果按 GitHub 相关性排序，不代表学习价值排名。")
        self.label(parent, "", 9, MUTED, anchor="w", wraplength=860, textvariable=status).pack(fill="x", pady=(0, 8))
        table_frame = tk.Frame(parent, bg=BG)
        table_frame.pack(fill="both", expand=True)
        table = ttk.Treeview(table_frame, columns=("name", "language", "updated"), show="headings", height=7, selectmode="browse")
        for name, text, width in [("name", "仓库", 480), ("language", "语言", 100), ("updated", "最近代码更新", 140)]:
            table.heading(name, text=text)
            table.column(name, width=width, minwidth=80)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        details = tk.StringVar(value="选择结果以查看描述。仓库描述属于作者主张；尚未审阅源码。")
        self.label(parent, "", 9, MUTED, anchor="w", justify="left", wraplength=860,
                   textvariable=details).pack(fill="x", pady=10)
        self.label(parent, "仓库首页链接（也可直接输入，跳过搜索）", 10, anchor="w").pack(fill="x", pady=(5, 5))
        repo_url = tk.StringVar(value=self.url.get() if self.url.get().startswith("https://github.com/") else "")
        ttk.Entry(parent, textvariable=repo_url).pack(fill="x")
        self.label(parent, "本次想学会什么？", 10, anchor="w").pack(fill="x", pady=(12, 5))
        goal = tk.StringVar(value=LEARNING_TRACKS[saved_track]["goal"])
        ttk.Entry(parent, textvariable=goal).pack(fill="x")

        def change_track(event=None):
            preset = LEARNING_TRACKS[track.get()]
            query.set(preset["query"])
            goal.set(preset["goal"])
            self.store.set("learning_track", track.get())
        track_choice.bind("<<ComboboxSelected>>", change_track)
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", pady=16)
        ttk.Button(actions, text="打开 GitHub", command=lambda: open_repo()).pack(side="left")
        ttk.Button(actions, text="生成学习计划  →", style="Primary.TButton", command=lambda: begin()).pack(side="right")
        results = []
        query_events = queue.Queue()
        search_cancel = threading.Event()
        active = {"searching": False}

        def select(event=None):
            selected = table.selection()
            if not selected:
                return
            item = results[int(selected[0])]
            repo_url.set(item["url"])
            details.set(item["description"] + "\n主题：" + (", ".join(item["topics"]) or "未标注") + " · 描述来自仓库，不代表已验证。")

        table.bind("<<TreeviewSelect>>", select)

        def poll_search():
            if not window.winfo_exists():
                search_cancel.set()
                return
            try:
                success, payload = query_events.get_nowait()
            except queue.Empty:
                window.after(150, poll_search)
                return
            active["searching"] = False
            search_button.configure(state="normal")
            if not success:
                status.set(payload)
                return
            results[:] = payload["items"]
            for item in table.get_children():
                table.delete(item)
            for index, item in enumerate(results):
                table.insert("", "end", iid=str(index), values=(item["name"], item["language"], item["updated"][:10]))
            status.set(f"找到 {payload['total']} 个匹配，显示前 {len(results)} 个。只取得元数据，尚未判断适合程度。"
                       + (" GitHub 表示搜索结果不完整。" if payload["incomplete"] else ""))
            details.set("选择项目后设置学习目标。若不适合你的阶段，研究员可以建议只学一个模块或暂缓。")

        def search():
            if active["searching"]:
                return
            active["searching"] = True
            search_button.configure(state="disabled")
            status.set("正在搜索 GitHub…")
            text, lang = query.get(), language.get()

            def worker():
                transport = Transport(search_cancel)
                try:
                    result = search_github(text, "" if lang == "不限语言" else lang, transport)
                    query_events.put((True, result))
                except Exception as exc:
                    query_events.put((False, str(exc) if isinstance(exc, UserError) else "搜索失败，请检查网络；也可以直接填写仓库链接。"))
                finally:
                    transport.close()
            threading.Thread(target=worker, daemon=True).start()
            window.after(150, poll_search)

        def open_repo():
            try:
                if not github_repo(repo_url.get()):
                    raise UserError("请填写 GitHub 仓库首页链接。")
                self.browser(repo_url.get())
            except UserError as exc:
                status.set(str(exc))

        def begin():
            link = repo_url.get().strip()
            try:
                if not github_repo(link):
                    raise UserError("请填写 GitHub 仓库首页链接。")
                if not goal.get().strip():
                    raise UserError("请填写一个具体的学习目标。")
                if not self.store.settings().get("model"):
                    status.set("请关闭此窗口，在左侧“模型连接”配置模型后，再生成学习计划。搜索不需要模型。")
                    return
            except UserError as exc:
                status.set(str(exc))
                return
            chosen_goal = goal.get().strip()
            chosen_track = track.get()
            self.store.set("learning_track", chosen_track)
            search_cancel.set()
            window.destroy()
            self.new()
            self.url.set(link)
            self.run(link, "", "我的 GitHub 学习方向：" + chosen_track + "\n学习目标：" + chosen_goal, None,
                     agent_focus=chosen_track == "AI Agent · 工程实践", learning_goal=chosen_goal, learning_track=chosen_track)

        search_button.configure(command=search)
        query_entry = row.winfo_children()[0]
        query_entry.bind("<Return>", lambda event: search())

    def _progress_ui(self, window, parent):
        projects = self.store.learning_projects()
        self.label(parent, "保存的学习计划", 11, anchor="w").pack(fill="x", pady=(15, 7))
        project_choice = ttk.Combobox(parent, state="readonly", values=[p['track'] + ' · ' + p['name'] + ' · ' + p['created'] for p in projects])
        project_choice.pack(fill="x")
        summary = tk.StringVar(value="还没有学习计划。先在“找项目 / 开始学习”选择仓库并生成计划。")
        self.label(parent, "", 9, MUTED, anchor="w", wraplength=870, justify="left", textvariable=summary).pack(fill="x", pady=9)
        pane = tk.PanedWindow(parent, orient="horizontal", bg=BG, sashwidth=8, bd=0)
        pane.pack(fill="both", expand=True)
        left, right = tk.Frame(pane, bg=BG), tk.Frame(pane, bg=BG)
        pane.add(left, minsize=240, width=265)
        pane.add(right, minsize=420)
        tasks_list = tk.Listbox(left, bg=CARD, fg=INK, font=(FONT, 10), relief="flat", bd=0,
                                selectbackground="#e3eaff", selectforeground=INK, exportselection=False)
        tasks_list.pack(fill="both", expand=True)
        task_details = ScrolledText(right, height=8, wrap="word", bg=CARD, fg=INK, font=(FONT, 10), relief="flat", padx=12, pady=10)
        task_details.pack(fill="both", expand=True)
        status = tk.StringVar(value="未开始")
        ttk.Combobox(right, textvariable=status, state="readonly", values=["未开始", "进行中", "已完成（自评）"]).pack(fill="x", pady=8)
        self.label(right, "我的结果、产物位置与卡点", 10, anchor="w").pack(fill="x", pady=(0, 5))
        notes = ScrolledText(right, height=4, wrap="word", bg=CARD, fg=INK, font=(FONT, 10), relief="flat", padx=10, pady=8)
        notes.pack(fill="x")
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", pady=13)
        state = {"project": None, "index": None}

        def refresh_tasks():
            project = state["project"]
            tasks_list.delete(0, "end")
            if not project:
                return
            for i, task in enumerate(project["tasks"]):
                tasks_list.insert("end", f"{i+1}. {task['title']} · {task['status']}")
            done = sum(t["status"] == "已完成（自评）" for t in project["tasks"])
            summary.set(f"方向：{project['track']} · 目标：{project['goal']}\n固定版本：{project['commit'][:12]} · 自评完成 {done}/{len(project['tasks'])}；完成标记不代表系统已验证掌握。")

        def select_task(event=None):
            selected = tasks_list.curselection()
            if not selected or not state["project"]:
                return
            state["index"] = selected[0]
            task = state["project"]["tasks"][selected[0]]
            task_details.configure(state="normal")
            task_details.delete("1.0", "end")
            labels = [("title", "任务"), ("reading", "阅读位置"), ("question", "先尝试回答"), ("exercise", "最小练习"), ("acceptance", "验收标准")]
            task_details.insert("1.0", "\n\n".join(title + "\n" + task[key] for key, title in labels))
            task_details.configure(state="disabled")
            status.set(task["status"])
            notes.delete("1.0", "end")
            notes.insert("1.0", task["notes"])

        def select_project(event=None):
            index = project_choice.current()
            if index < 0:
                return
            state.update(project=projects[index], index=None)
            refresh_tasks()
            tasks_list.selection_set(0)
            select_task()

        def save():
            project, index = state["project"], state["index"]
            if project is None or index is None:
                return
            text = notes.get("1.0", "end-1c")
            try:
                self.store.update_learning_task(project["id"], index, status.get(), text)
            except UserError as exc:
                messagebox.showerror("记录未保存", str(exc), parent=window)
                return
            project["tasks"][index].update(status=status.get(), notes=text)
            refresh_tasks()
            tasks_list.selection_set(index)
            self.status.set("学习进度已保存；完成状态为用户自评。")

        def open_report():
            if not state["project"]:
                return
            item = self.store.report(state["project"]["report_id"])
            self.current, self.report_id = item, item["id"]
            self.accumulated, self.evidence = item["report"], item["evidence"]
            self.evidence_list.delete(0, "end")
            for evidence in self.evidence:
                self.add_evidence(evidence)
            self.render(self.accumulated)
            window.destroy()
            self.notebook.select(0)
            self.status.set("已打开学习报告，可结合当前任务继续追问。")

        def hint():
            project, index = state["project"], state["index"]
            if project is None or index is None:
                return
            task = project["tasks"][index]
            question = ("学习方向：" + project["track"] + "\n我正在做 GitHub 学习任务：" + task["title"] + "\n阅读位置：" + task["reading"]
                        + "\n要回答：" + task["question"] + "\n验收标准：" + task["acceptance"]
                        + "\n我的尝试/卡点：" + (notes.get("1.0", "end-1c").strip() or "尚未记录")
                        + "\n请依据已读材料给一个下一步提示或定位方法，先不要代做整个练习；不要假定我已完成。")
            open_report()
            self.followup.set(question)
            self.status.set("提示问题已填入追问框；点击“继续追问”发送。")

        def export():
            project = state["project"]
            if not project:
                return
            filename = filedialog.asksaveasfilename(parent=window, title="导出学习记录", defaultextension=".md",
                                                    initialfile=project["name"].replace("/", "-") + "-学习记录.md", filetypes=[("Markdown", "*.md")])
            if not filename:
                return
            blocks = [f"# {project['name']} 学习记录\n\n方向：{project['track']}\n\n目标：{project['goal']}\n\n仓库：{project['url']}\n\n固定 commit：{project['commit']}\n\n完成状态为用户自评，未经系统验证。"]
            for task in project["tasks"]:
                blocks.append("## " + task["title"] + "\n\n" + "\n\n".join(label + "：" + task[key] for key, label in [
                    ("status", "状态"), ("reading", "阅读"), ("question", "问题"), ("exercise", "练习"), ("acceptance", "验收"), ("notes", "实际记录")]))
            try:
                Path(filename).write_text("\n\n".join(blocks), encoding="utf-8")
                self.status.set("学习记录已导出。")
            except OSError:
                messagebox.showerror("导出失败", "无法写入所选文件。", parent=window)

        ttk.Button(actions, text="打开学习报告", command=open_report).pack(side="left")
        ttk.Button(actions, text="准备下一步提示", command=hint).pack(side="left", padx=7)
        ttk.Button(actions, text="导出记录", command=export).pack(side="left")
        ttk.Button(actions, text="保存进度", command=save, style="Primary.TButton").pack(side="right")
        self.label(parent, "先保存记录再切换任务。准备提示会填入主窗口，由你点击发送。", 9, MUTED, anchor="w").pack(fill="x", pady=(0, 8))
        tasks_list.bind("<<ListboxSelect>>", select_task)
        project_choice.bind("<<ComboboxSelected>>", select_project)
        if projects:
            project_choice.current(0)
            select_project()
