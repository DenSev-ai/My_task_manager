"""Tkinter GUI for Task Reminder in Todoist-like style.

The module provides:
- TaskFilterBar: top filter buttons (All / Today / Tomorrow / By date).
- ProjectSidebar: left panel listing projects with add/remove/move buttons.
- TaskListView: right panel listing tasks for the selected project.
- MainWindow: assembles the layout and wires callbacks.

All date/time values are stored in UTC; local time is used for display.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from db import DatabaseManager, Project, Task, TaskLimitExceeded, TaskStatus
from ui.datetime_picker import DateTimePicker, local_to_utc


class TaskFilterBar(ttk.Frame):
    """Top bar with task filter buttons."""

    FILTERS = {
        "all": "Все задачи",
        "today": "Сегодня",
        "tomorrow": "Завтра",
        "date": "По дате",
    }

    def __init__(
        self,
        parent: tk.Widget,
        on_filter_changed: Callable[[str, datetime | None], None],
    ) -> None:
        super().__init__(parent, padding=5)
        self.on_filter_changed = on_filter_changed
        self._buttons: dict[str, ttk.Button] = {}
        self._selected = "all"

        for key, label in self.FILTERS.items():
            btn = ttk.Button(
                self,
                text=label,
                command=lambda k=key: self._select_filter(k),
            )
            btn.pack(side=tk.LEFT, padx=2)
            self._buttons[key] = btn

        self._update_style()

    def _select_filter(self, key: str) -> None:
        selected_date: datetime | None = None
        if key == "date":
            # Will be replaced by DateTimePicker integration in Step 3.
            # For now we open a simple date dialog.
            selected_date = self._ask_date()
            if selected_date is None:
                return
        self._selected = key
        self._update_style()
        self.on_filter_changed(key, selected_date)

    def _ask_date(self) -> datetime | None:
        picker = DateTimePicker(self)
        local_dt = picker.ask()
        if local_dt is None:
            return None
        return local_to_utc(local_dt)

    def _update_style(self) -> None:
        for key, btn in self._buttons.items():
            if key == self._selected:
                btn.configure(style="Accent.TButton")
            else:
                btn.configure(style="TButton")


class ProjectSidebar(ttk.Frame):
    """Left sidebar showing projects."""

    def __init__(
        self,
        parent: tk.Widget,
        db: DatabaseManager,
        on_project_selected: Callable[[int | None], None],
    ) -> None:
        super().__init__(parent, width=250, padding=10)
        self.pack_propagate(False)
        self.db = db
        self.on_project_selected = on_project_selected
        self._selected_project_id: int | None = None

        ttk.Label(self, text="Проекты", font=("Segoe UI", 14, "bold")).pack(
            anchor=tk.W, pady=(0, 10)
        )

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="+", width=3, command=self._add_project).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="-", width=3, command=self._delete_project).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            btn_frame, text="↑", width=3, command=self._move_project_up
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_frame, text="↓", width=3, command=self._move_project_down
        ).pack(side=tk.LEFT, padx=2)

        self.listbox = tk.Listbox(
            self,
            selectmode=tk.SINGLE,
            activestyle="none",
            font=("Segoe UI", 11),
            bg="#fafafa",
            fg="#202020",
            selectbackground="#e44332",
            selectforeground="white",
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        self.refresh()

    def refresh(self) -> None:
        self.listbox.delete(0, tk.END)
        for project in self.db.get_projects():
            display = f"{project.name}\n  {project.description}"
            self.listbox.insert(tk.END, display)
            if project.id == self._selected_project_id:
                self.listbox.selection_set(tk.END)

    def _on_select(self, _event: Any) -> None:
        index = self.listbox.curselection()
        if not index:
            return
        project = self.db.get_projects()[index[0]]
        self._selected_project_id = project.id
        self.on_project_selected(project.id)

    def _add_project(self) -> None:
        name = simpledialog.askstring("Новый проект", "Название проекта:")
        if not name:
            return
        description = simpledialog.askstring(
            "Новый проект", "Описание проекта (2 строки):"
        )
        self.db.create_project(name, description or "")
        self.refresh()

    def _delete_project(self) -> None:
        project_id = self._get_selected_id()
        if project_id is None:
            return
        if messagebox.askyesno(
            "Удалить проект", "Удалить проект и все его задачи?"
        ):
            self.db.delete_project(project_id)
            self._selected_project_id = None
            self.refresh()
            self.on_project_selected(None)

    def _move_project_up(self) -> None:
        project_id = self._get_selected_id()
        if project_id is None:
            return
        self.db.move_project_up(project_id)
        self.refresh()

    def _move_project_down(self) -> None:
        project_id = self._get_selected_id()
        if project_id is None:
            return
        self.db.move_project_down(project_id)
        self.refresh()

    def _get_selected_id(self) -> int | None:
        index = self.listbox.curselection()
        if not index:
            return None
        return self.db.get_projects()[index[0]].id


class TaskListView(ttk.Frame):
    """Right panel showing tasks for the selected project."""

    def __init__(
        self,
        parent: tk.Widget,
        db: DatabaseManager,
        on_task_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=10)
        self.db = db
        self.on_task_changed = on_task_changed
        self._project_id: int | None = None
        self._filter = "all"
        self._filter_date: datetime | None = None

        ttk.Label(self, text="Задачи", font=("Segoe UI", 14, "bold")).pack(
            anchor=tk.W, pady=(0, 10)
        )

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="+", width=3, command=self._add_task).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="-", width=3, command=self._delete_task).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="↑", width=3, command=self._move_task_up).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="↓", width=3, command=self._move_task_down).pack(
            side=tk.LEFT, padx=2
        )

        self.tree = ttk.Treeview(
            self,
            columns=("status", "name", "due"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("status", text="Статус")
        self.tree.heading("name", text="Задача")
        self.tree.heading("due", text="Срок")
        self.tree.column("status", width=80, anchor=tk.CENTER)
        self.tree.column("name", width=300)
        self.tree.column("due", width=150)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=5)

        # Checkbox column uses a button-like cell; we'll render status text for now.
        self.tree.bind("<Double-1>", self._toggle_status)

    def set_project(self, project_id: int | None) -> None:
        self._project_id = project_id
        self.refresh()

    def set_filter(self, filter_key: str, filter_date: datetime | None = None) -> None:
        self._filter = filter_key
        self._filter_date = filter_date
        self.refresh()

    def refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        if self._project_id is None:
            return

        if self._filter == "today":
            tasks = self.db.get_tasks_for_today(self._project_id)
        elif self._filter == "tomorrow":
            tasks = self.db.get_tasks_for_tomorrow(self._project_id)
        elif self._filter == "date" and self._filter_date is not None:
            tasks = self.db.get_tasks_for_date(self._filter_date, self._project_id)
        else:
            tasks = self.db.get_tasks_by_project(self._project_id)

        for task in tasks:
            status_text = "✓" if task.status == TaskStatus.DONE else "☐"
            due_local = task.due_date_utc.astimezone()
            due_str = due_local.strftime("%d.%m.%Y %H:%M")
            self.tree.insert(
                "",
                tk.END,
                iid=str(task.id),
                values=(status_text, task.name, due_str),
                tags=("done" if task.status == TaskStatus.DONE else "pending",),
            )

    def _add_task(self) -> None:
        if self._project_id is None:
            messagebox.showwarning("Нет проекта", "Сначала выберите проект")
            return
        name = simpledialog.askstring("Новая задача", "Название задачи:")
        if not name:
            return
        description = simpledialog.askstring(
            "Новая задача", "Описание задачи (2 строки):"
        )
        picker = DateTimePicker(self)
        due_local = picker.ask()
        due_utc = local_to_utc(due_local) if due_local else None
        try:
            self.db.create_task(
                self._project_id,
                name,
                description or "",
                due_date_utc=due_utc,
            )
        except TaskLimitExceeded:
            messagebox.showerror(
                "Лимит задач",
                "В проекте может быть максимум 10 задач. "
                "Удалите одну из задач или создайте новый проект.",
            )
            return
        self.refresh()
        if self.on_task_changed:
            self.on_task_changed()

    def _delete_task(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        if messagebox.askyesno("Удалить задачу", "Удалить выбранную задачу?"):
            self.db.delete_task(task_id)
            self.refresh()
            if self.on_task_changed:
                self.on_task_changed()

    def _move_task_up(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        self.db.move_task_up(task_id)
        self.refresh()

    def _move_task_down(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        self.db.move_task_down(task_id)
        self.refresh()

    def _toggle_status(self, _event: Any) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return
        task = self.db.get_task(task_id)
        new_status = (
            TaskStatus.DONE
            if task.status != TaskStatus.DONE
            else TaskStatus.PENDING
        )
        self.db.update_task(task_id, status=new_status)
        self.refresh()
        if self.on_task_changed:
            self.on_task_changed()

    def _get_selected_task_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])


class MainWindow:
    """Main application window."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.root = tk.Tk()
        self.root.title("Task Reminder")
        self.root.geometry("900x600")
        self.root.configure(bg="#ffffff")

        self._setup_styles()

        self.filter_bar = TaskFilterBar(
            self.root,
            on_filter_changed=self._on_filter_changed,
        )
        self.filter_bar.pack(fill=tk.X, side=tk.TOP)

        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        self.sidebar = ProjectSidebar(
            self.paned,
            db=self.db,
            on_project_selected=self._on_project_selected,
        )
        self.paned.add(self.sidebar, weight=1)

        self.task_view = TaskListView(
            self.paned,
            db=self.db,
            on_task_changed=self.sidebar.refresh,
        )
        self.paned.add(self.task_view, weight=3)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("vista")
        style.configure("TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            foreground="#e44332",
        )

    def _on_project_selected(self, project_id: int | None) -> None:
        self.task_view.set_project(project_id)

    def _on_filter_changed(self, filter_key: str, filter_date: datetime | None) -> None:
        self.task_view.set_filter(filter_key, filter_date)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    # Minimal standalone launch for development / manual testing.
    db = DatabaseManager("tasks.db")
    app = MainWindow(db)
    app.run()
