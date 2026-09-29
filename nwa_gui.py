#!/usr/bin/env python3
"""Japanese Windows desktop interface for NWA to MP3."""

from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from app_paths import get_settings, resource_path, save_settings, user_data_dir
from nwa_conversion import (
    Job, OUTPUT_FORMATS, SetupError, build_jobs, convert_batch, discover_sources,
    ensure_ffmpeg, ensure_mp3_encoder,
)
from tool_setup import check_tools, install_tool, load_catalog, save_tool_path


QUALITY_CHOICES = {
    "おすすめ（標準）": 2,
    "容量を小さく": 5,
    "高音質": 0,
}
BITRATES = ("", "128k", "160k", "192k", "224k", "256k", "320k")
FORMAT_LABELS = {"mp3": "MP3", "wav": "WAV", "flac": "FLAC"}
FFMPEG_INSTALL_COMMAND = "winget install --id Gyan.FFmpeg --exact --source winget"


class NwaApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NWA 音声変換")
        self.root.geometry("760x630")
        self.root.minsize(700, 540)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.settings = get_settings()
        self.tool_status: dict[str, tuple[bool, str]] = {}
        self.setup_window: tk.Toplevel | None = None
        self.setup_progress: ttk.Progressbar | None = None
        self.setup_status: ttk.Label | None = None
        self.setup_actions: list[ttk.Button] = []
        self.setup_cancel_button: ttk.Button | None = None
        self.setup_busy = False
        self.guide_window: tk.Toplevel | None = None
        self.pending_close = False
        self.preview_revision = 0
        self.preview_after_id: str | None = None
        self.preview_signature: tuple[str, str, bool, bool, str, str] | None = None
        self.preview_jobs: list[Job] = []
        self.input_path = tk.StringVar(value=str(self.settings.get("last_input", "")))
        self.output_path = tk.StringVar(value=str(self.settings.get("last_output", "")))
        self.recursive = tk.BooleanVar(value=bool(self.settings.get("recursive", False)))
        remembered = str(self.settings.get("quality_preset", "おすすめ（標準）"))
        self.quality = tk.StringVar(value=remembered if remembered in QUALITY_CHOICES else "おすすめ（標準）")
        self.bitrate = tk.StringVar(value=str(self.settings.get("bitrate", "")))
        self.overwrite = tk.BooleanVar(value=bool(self.settings.get("overwrite", False)))
        remembered_format = str(self.settings.get("output_format", "mp3")).casefold()
        self.output_format = tk.StringVar(
            value=remembered_format if remembered_format in OUTPUT_FORMATS else "mp3"
        )
        self.output_is_default = bool(self.settings.get("output_is_default", not self.output_path.get().strip()))
        self.tool_status_text = tk.StringVar(value="変換ツールを確認しています…")
        self.preview_text = tk.StringVar(value="NWAファイルまたはフォルダーを選んでください。")
        self.progress_text = tk.StringVar(value="待機中")
        self.result_text = tk.StringVar(value="成功 0 ／ スキップ 0 ／ 失敗 0")
        self._build_window()
        self.root.protocol("WM_DELETE_WINDOW", self._close_request)
        self.input_path.trace_add("write", self._refresh_preview)
        self.output_path.trace_add("write", self._refresh_preview)
        self.recursive.trace_add("write", self._refresh_preview)
        self.overwrite.trace_add("write", self._refresh_preview)
        self.quality.trace_add("write", self._refresh_preview)
        self.output_format.trace_add("write", self._format_changed)
        self.root.after(80, self._drain_events)
        self._start_worker("tool_check", self._check_tools_worker)

    def _build_window(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(11, weight=1)

        ttk.Label(outer, text="NWA → MP3 / WAV / FLAC", font=("Yu Gothic UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        ttk.Label(outer, text="はじめて使う場合は、まず変換ツールを準備します。").grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(outer, textvariable=self.tool_status_text).grid(
            row=1, column=2, sticky="e"
        )
        self.setup_button = ttk.Button(
            outer, text="必要なツールを確認・準備", command=self._open_setup
        )
        self.setup_button.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 14))

        ttk.Separator(outer).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(outer, text="1. 入力").grid(row=4, column=0, sticky="w", pady=4)
        self.input_entry = ttk.Entry(outer, textvariable=self.input_path)
        self.input_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=4)
        self.choose_file_button = ttk.Button(outer, text="ファイルを選ぶ", command=self._choose_file)
        self.choose_file_button.grid(row=4, column=2, sticky="ew", pady=4)
        self.choose_folder_button = ttk.Button(outer, text="フォルダーを選ぶ", command=self._choose_folder)
        self.choose_folder_button.grid(row=5, column=2, sticky="ew", pady=4)
        self.recursive_box = ttk.Checkbutton(
            outer, text="サブフォルダーも検索する", variable=self.recursive
        )
        self.recursive_box.grid(row=5, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(outer, text="2. 保存先").grid(row=6, column=0, sticky="w", pady=4)
        self.output_entry = ttk.Entry(outer, textvariable=self.output_path)
        self.output_entry.grid(row=6, column=1, sticky="ew", padx=8, pady=4)
        self.choose_output_button = ttk.Button(outer, text="変更", command=self._choose_output)
        self.choose_output_button.grid(row=6, column=2, sticky="ew", pady=4)

        ttk.Label(outer, text="3. MP3音質").grid(row=7, column=0, sticky="w", pady=(8, 4))
        self.quality_box = ttk.Combobox(
            outer, textvariable=self.quality, values=tuple(QUALITY_CHOICES),
            state="readonly", width=22,
        )
        self.quality_box.grid(row=7, column=1, sticky="w", padx=8, pady=(8, 4))
        self.details_button = ttk.Button(outer, text="詳細設定", command=self._toggle_details)
        self.details_button.grid(row=7, column=2, sticky="e", pady=(8, 4))
        ttk.Label(outer, text="4. 出力形式").grid(row=8, column=0, sticky="w", pady=4)
        self.output_format_box = ttk.Combobox(
            outer, textvariable=self.output_format,
            values=tuple(OUTPUT_FORMATS), state="readonly", width=12,
        )
        self.output_format_box.grid(row=8, column=1, sticky="w", padx=8, pady=4)
        self.overwrite_box = ttk.Checkbutton(
            outer, text="既存の出力ファイルを置き換える", variable=self.overwrite
        )
        self.overwrite_box.grid(row=8, column=2, sticky="w", pady=4)
        self.details_frame = ttk.Frame(outer)
        self.details_frame.columnconfigure(1, weight=1)
        ttk.Label(self.details_frame, text="MP3固定ビットレート").grid(row=0, column=0, sticky="w")
        self.bitrate_box = ttk.Combobox(
            self.details_frame, textvariable=self.bitrate, values=BITRATES,
            state="readonly", width=10,
        )
        self.bitrate_box.grid(row=0, column=1, sticky="w", padx=8)
        self.bitrate.trace_add("write", self._refresh_preview)
        self.quality_box.configure(state="disabled" if self.output_format.get() != "mp3" else "readonly")
        self.details_button.configure(state="disabled" if self.output_format.get() != "mp3" else "normal")

        preview = ttk.LabelFrame(outer, text="変換予定", padding=8)
        preview.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        preview.columnconfigure(0, weight=1)
        ttk.Label(preview, textvariable=self.preview_text, wraplength=680).grid(
            row=0, column=0, sticky="w"
        )

        work = ttk.LabelFrame(outer, text="進行状況", padding=8)
        work.grid(row=11, column=0, columnspan=3, sticky="nsew", pady=4)
        work.columnconfigure(0, weight=1)
        work.rowconfigure(2, weight=1)
        ttk.Label(work, textvariable=self.progress_text).grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(work, mode="determinate", maximum=1)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=5)
        self.log_box = tk.Text(work, height=5, wrap="word", state="disabled")
        self.log_box.grid(row=2, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(work, orient="vertical", command=self.log_box.yview)
        log_scroll.grid(row=2, column=1, sticky="ns")
        self.log_box.configure(yscrollcommand=log_scroll.set)

        footer = ttk.Frame(outer)
        footer.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.result_text).grid(row=0, column=0, sticky="w")
        self.open_output_button = ttk.Button(
            footer, text="保存先を開く", command=self._open_output, state="disabled"
        )
        self.open_output_button.grid(row=0, column=1, padx=(4, 8))
        self.cancel_button = ttk.Button(footer, text="中止", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=4)
        self.save_log_button = ttk.Button(footer, text="ログを保存", command=self._save_log)
        self.save_log_button.grid(row=0, column=3, padx=4)
        self.start_button = ttk.Button(footer, text="変換開始", command=self._start_conversion)
        self.start_button.grid(row=0, column=4, padx=(4, 0))

    def _start_worker(self, name: str, target: Any, *args: Any) -> None:
        if self.worker and self.worker.is_alive():
            return

        def run() -> None:
            try:
                result = target(*args)
                self.events.put((f"{name}_done", result))
            except Exception as exc:  # Display actionable errors in the UI.
                self.events.put((f"{name}_error", exc))

        self.worker = threading.Thread(target=run, name=f"nwa-{name}", daemon=True)
        self.worker.start()

    def _check_tools_worker(self) -> dict[str, tuple[bool, str]]:
        return check_tools(self.settings)

    def _refresh_preview(self, *_args: Any) -> None:
        raw_input = self.input_path.get().strip()
        if not raw_input:
            self.preview_text.set("NWAファイルまたはフォルダーを選んでください。")
            self.preview_jobs = []
            self.preview_signature = None
            return
        self.preview_revision += 1
        revision = self.preview_revision
        signature = self._selection_signature()
        self.preview_text.set("対象を確認しています…")
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(180, lambda: self._start_preview(revision, signature))

    def _selection_signature(self) -> tuple[str, str, bool, bool, str, str, str]:
        return (
            self.input_path.get().strip(), self.output_path.get().strip(),
            self.recursive.get(), self.overwrite.get(), self.quality.get(), self.bitrate.get(),
            self.output_format.get(),
        )

    def _format_changed(self, *_args: Any) -> None:
        if self.output_format.get() not in OUTPUT_FORMATS:
            return
        is_mp3 = self.output_format.get() == "mp3"
        self.quality_box.configure(state="readonly" if is_mp3 else "disabled")
        self.details_button.configure(state="normal" if is_mp3 else "disabled")
        if not is_mp3 and self.details_frame.winfo_manager():
            self.details_frame.grid_remove()
            self.details_button.configure(text="詳細設定（MP3）")
        elif is_mp3:
            self.details_button.configure(text="詳細設定")

        raw_input = self.input_path.get().strip()
        if self.output_is_default and raw_input:
            source = Path(raw_input).expanduser().resolve()
            input_root = source if source.is_dir() else source.parent
            folder = "mp3" if is_mp3 else self.output_format.get()
            self.output_path.set(str(input_root / folder))
        self._refresh_preview()

    def _start_preview(
        self, revision: int,
        signature: tuple[str, str, bool, bool, str, str, str],
    ) -> None:
        self.preview_after_id = None

        def summarize() -> None:
            try:
                raw_input, raw_output, recursive, overwrite, quality, bitrate, output_format = signature
                source = Path(raw_input).expanduser().resolve()
                sources = discover_sources(source, recursive)
                root = source if source.is_dir() else source.parent
                default_folder = "mp3" if output_format == "mp3" else output_format
                output = Path(raw_output).expanduser().resolve() if raw_output else root / default_folder
                jobs = build_jobs(sources, root, output, output_format)
                skips = sum(job.output.exists() for job in jobs) if not overwrite else 0
                text = f"対象 {len(jobs)} 曲 ／ 既存出力 {skips} 曲（スキップ予定）\n保存先: {output}"
                text += f"\n形式: {FORMAT_LABELS[output_format]}"
                if output_format == "mp3":
                    text += f"\n音質: 固定ビットレート {bitrate}" if bitrate else f"\n音質: {quality}"
                else:
                    text += "\n音質: 無劣化形式（WAV/FLAC）"
                result: Any = (jobs, text)
            except (OSError, SetupError, ValueError) as exc:
                result = ([], str(exc))
            self.events.put(("preview_done", (revision, signature, result)))

        threading.Thread(target=summarize, name="nwa-preview", daemon=True).start()

    def _choose_file(self) -> None:
        value = filedialog.askopenfilename(
            title="NWAファイルを選択", filetypes=(("NWA音声", "*.nwa *.NWA"), ("すべてのファイル", "*.*")),
        )
        if value:
            self.input_path.set(value)
            self.recursive.set(False)
            if self.output_is_default:
                folder = "mp3" if self.output_format.get() == "mp3" else self.output_format.get()
                self.output_path.set(str(Path(value).resolve().parent / folder))

    def _choose_folder(self) -> None:
        value = filedialog.askdirectory(title="NWAファイルを含むフォルダーを選択")
        if value:
            self.input_path.set(value)
            if self.output_is_default:
                folder = "mp3" if self.output_format.get() == "mp3" else self.output_format.get()
                self.output_path.set(str(Path(value).resolve() / folder))

    def _choose_output(self) -> None:
        value = filedialog.askdirectory(title="音声ファイルの保存先を選択", mustexist=False)
        if value:
            self.output_is_default = False
            self.output_path.set(value)

    def _toggle_details(self) -> None:
        if self.details_frame.winfo_manager():
            self.details_frame.grid_remove()
            self.details_button.configure(text="詳細設定")
        else:
            self.details_frame.grid(row=9, column=0, columnspan=3, sticky="ew", pady=4)
            self.details_button.configure(text="詳細設定を閉じる")

    def _get_jobs(self) -> list[Job]:
        if self.preview_signature == self._selection_signature() and self.preview_jobs:
            return list(self.preview_jobs)
        raw = self.input_path.get().strip()
        if not raw:
            raise SetupError("先にNWAファイルまたはフォルダーを選んでください。")
        source = Path(raw).expanduser().resolve()
        sources = discover_sources(source, self.recursive.get())
        root = source if source.is_dir() else source.parent
        output_format = self.output_format.get()
        default_folder = "mp3" if output_format == "mp3" else output_format
        output = Path(self.output_path.get()).expanduser().resolve() if self.output_path.get().strip() else root / default_folder
        return build_jobs(sources, root, output, output_format)

    def _save_preferences(self) -> None:
        updated = dict(self.settings)
        updated.update({
            "last_input": self.input_path.get().strip(),
            "last_output": self.output_path.get().strip(),
            "recursive": self.recursive.get(),
            "quality_preset": self.quality.get(),
            "bitrate": self.bitrate.get(),
            "overwrite": self.overwrite.get(),
            "output_format": self.output_format.get(),
            "output_is_default": self.output_is_default,
        })
        try:
            save_settings(updated)
            self.settings = updated
        except OSError as exc:
            self._append_log(f"設定を保存できませんでした: {exc}")

    def _start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        missing = [name for name, (ready, _detail) in self.tool_status.items() if not ready]
        if missing:
            messagebox.showinfo("ツールの準備", "先に『必要なツールを確認・準備』から変換ツールを準備してください。", parent=self.root)
            self._open_setup()
            return
        try:
            jobs = self._get_jobs()
        except (SetupError, OSError, ValueError) as exc:
            messagebox.showerror("入力を確認してください", str(exc), parent=self.root)
            return
        try:
            self.settings = get_settings()
            self._save_preferences()
            settings = self.settings
            vgmstream = self._resolved_tool("vgmstream", settings)
            ffmpeg = self._resolved_tool("ffmpeg", settings)
            output_format = self.output_format.get()
            ensure_ffmpeg(ffmpeg)
            if output_format == "mp3":
                ensure_mp3_encoder(ffmpeg)
            quality = None if self.bitrate.get() else QUALITY_CHOICES.get(self.quality.get(), 2)
            bitrate = self.bitrate.get() or None
            overwrite = self.overwrite.get()
        except (OSError, SetupError) as exc:
            messagebox.showerror("ツールを確認してください", str(exc), parent=self.root)
            return
        self._append_log(f"変換を開始します（{len(jobs)} 曲）。")
        self.progress_bar.configure(maximum=len(jobs), value=0)
        self.progress_text.set("準備中")
        self.result_text.set("成功 0 ／ スキップ 0 ／ 失敗 0")
        self.cancel_event = threading.Event()
        self.cancel_button.configure(state="normal")
        self.start_button.configure(state="disabled")
        self.setup_button.configure(state="disabled")
        self._set_conversion_controls(True)

        def run() -> Any:
            result = convert_batch(
                jobs, vgmstream, ffmpeg, quality, bitrate, overwrite,
                cancel_event=self.cancel_event,
                progress=lambda stage, source, index, total: self.events.put(
                    ("conversion_progress", (stage, source, index, total))
                ),
                output_format=output_format,
            )
            return result

        self._start_worker("conversion", run)

    @staticmethod
    def _resolved_tool(name: str, settings: dict[str, Any]) -> str:
        ready, detail = check_tools(settings).get(name, (False, "未確認"))
        if not ready:
            raise SetupError(detail)
        return detail

    def _output_directory(self) -> Path:
        if self.output_path.get().strip():
            return Path(self.output_path.get()).expanduser().resolve()
        source = Path(self.input_path.get()).expanduser().resolve()
        output_format = self.output_format.get()
        folder = "mp3" if output_format == "mp3" else output_format
        return (source if source.is_dir() else source.parent) / folder

    def _cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.progress_text.set("中止しています。しばらくお待ちください…")
            if self.setup_busy and self.setup_status:
                self.setup_status.configure(text="導入を中止しています。しばらくお待ちください…")
                if self.setup_cancel_button:
                    self.setup_cancel_button.configure(state="disabled")

    def _open_output(self) -> None:
        try:
            target = self._output_directory()
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(target)  # type: ignore[attr-defined]
        except (OSError, SetupError) as exc:
            messagebox.showerror("保存先を開けません", str(exc), parent=self.root)

    def _save_log(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="進行状況を保存", defaultextension=".txt",
            filetypes=(("テキストファイル", "*.txt"),),
        )
        if not destination:
            return
        try:
            text = self.log_box.get("1.0", "end-1c")
            Path(destination).write_text(text + "\n", encoding="utf-8")
            messagebox.showinfo("ログを保存しました", f"保存先: {destination}", parent=self.root)
        except OSError as exc:
            messagebox.showerror("ログを保存できません", str(exc), parent=self.root)

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text.rstrip() + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _open_setup(self) -> None:
        if self.setup_window and self.setup_window.winfo_exists():
            self.setup_window.deiconify()
            self.setup_window.lift()
            return
        self.setup_window = tk.Toplevel(self.root)
        window = self.setup_window
        window.title("変換ツールの準備")
        window.transient(self.root)
        window.geometry("860x540")
        window.minsize(780, 480)
        frame = ttk.Frame(window, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(3, weight=0)
        ttk.Label(frame, text="手動で準備する場合はセットアップガイドをご覧ください。自動ダウンロードも任意で使えます。", wraplength=790).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        self.setup_actions = []
        for row, key in enumerate(("vgmstream", "ffmpeg"), start=1):
            definition = load_catalog()[key]
            title = str(definition["display_name"])
            ttk.Label(frame, text=f"{title}（{definition['version']}）").grid(
                row=row, column=0, sticky="w", pady=5
            )
            download_button = ttk.Button(frame, text="自動ダウンロード", command=lambda name=key: self._install(name))
            download_button.grid(row=row, column=1, padx=4, pady=5)
            choose_button = ttk.Button(frame, text="実行ファイルを選ぶ", command=lambda name=key: self._choose_tool(name))
            choose_button.grid(row=row, column=2, padx=4, pady=5)
            self.setup_actions.extend((download_button, choose_button))
            ttk.Button(frame, text="配布元を開く", command=lambda url=str(definition["homepage"]): webbrowser.open(url)).grid(
                row=row, column=3, padx=4, pady=3
            )
        ttk.Label(frame, text="FFmpegはWindowsのターミナルからも導入できます：").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 2)
        )
        ttk.Label(frame, text=FFMPEG_INSTALL_COMMAND).grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(frame, text="コマンドをコピー", command=self._copy_ffmpeg_command).grid(row=4, column=3, padx=4)
        ttk.Label(frame, text="wingetで導入した後はアプリを再起動してください。検出できなければ実行ファイルを選べます。").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=4
        )
        ttk.Separator(frame).grid(row=6, column=0, columnspan=4, sticky="ew", pady=10)
        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=4, sticky="ew")
        ttk.Button(actions, text="セットアップガイド", command=self._open_guide).pack(side="left", padx=(0, 8))
        for text, command in (
            ("再確認", self._recheck_tools),
            ("必要なツールをまとめて導入", self._install_all),
            ("ダウンロード済みZIPを選ぶ", self._choose_zip),
        ):
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side="left", padx=(0, 8))
            self.setup_actions.append(button)
        self.setup_cancel_button = ttk.Button(actions, text="中止", command=self._cancel, state="disabled")
        self.setup_cancel_button.pack(side="left")
        self.setup_status = ttk.Label(frame, text="", wraplength=790)
        self.setup_status.grid(row=8, column=0, columnspan=4, sticky="w", pady=(12, 4))
        self.setup_progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.setup_progress.grid(row=9, column=0, columnspan=4, sticky="ew", pady=5)
        ttk.Label(frame, text=f"自動導入の保存先: {user_data_dir() / 'tools'}", wraplength=790).grid(
            row=10, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        window.protocol("WM_DELETE_WINDOW", window.withdraw)
        self._update_setup_status()

    def _update_setup_status(
        self, status: dict[str, tuple[bool, str]] | None = None,
        *, hide_when_ready: bool = True,
    ) -> None:
        self.settings = get_settings()
        self.tool_status = status if status is not None else check_tools(self.settings)
        lines = []
        for name, label in (("vgmstream", "音声読み取り"), ("ffmpeg", "音声ファイル作成")):
            ready, detail = self.tool_status[name]
            if name == "ffmpeg":
                label = "音声ファイル作成"
            lines.append(f"{label}: {'準備済み' if ready else '未準備'} — {detail}")
        if self.setup_status:
            self.setup_status.configure(text="\n".join(lines))
        self.start_button.configure(state="normal")
        self.tool_status_text.set("変換ツールの準備ができました。" if all(ready for ready, _ in self.tool_status.values()) else "初回セットアップが必要です。")
        if hide_when_ready and all(ready for ready, _ in self.tool_status.values()) and self.setup_window:
            self.setup_window.withdraw()

    def _recheck_tools(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.settings = get_settings()
        self.tool_status_text.set("変換ツールを確認しています…")
        self._start_worker("tool_check", self._check_tools_worker)

    def _copy_ffmpeg_command(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(FFMPEG_INSTALL_COMMAND)

    def _open_guide(self) -> None:
        if self.guide_window and self.guide_window.winfo_exists():
            self.guide_window.deiconify()
            self.guide_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.guide_window = window
        window.title("セットアップガイド")
        window.geometry("780x560")
        window.minsize(600, 400)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        guide = tk.Text(window, wrap="word", padx=16, pady=16, font=("Yu Gothic UI", 10))
        guide.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(window, command=guide.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        guide.configure(yscrollcommand=scroll.set)
        try:
            text = resource_path("docs/SETUP.md").read_text(encoding="utf-8")
        except OSError as exc:
            text = f"ガイドを読み込めません: {exc}\n\nFFmpegの導入コマンド:\n{FFMPEG_INSTALL_COMMAND}"
        guide.tag_configure("heading", font=("Yu Gothic UI", 12, "bold"), spacing1=8, spacing3=4)
        guide.tag_configure("code", font=("Consolas", 10), spacing1=4, spacing3=4)
        code = False
        for line in text.splitlines():
            if line.startswith("```"):
                code = not code
                continue
            tag = "code" if code else ""
            if line.startswith("#"):
                tag = "heading"
                line = line.lstrip("# ")
            line = re.sub(r"\[([^\]]+)\]\((https://[^)]+)\)", r"\1: \2", line)
            guide.insert("end", line.replace("`", "") + "\n", tag)
        guide.configure(state="disabled")
        buttons = ttk.Frame(window, padding=8)
        buttons.grid(row=1, column=0, columnspan=2)
        ttk.Button(buttons, text="FFmpegコマンドをコピー", command=self._copy_ffmpeg_command).pack(side="left", padx=4)
        ttk.Button(buttons, text="vgmstream配布元", command=lambda: webbrowser.open("https://vgmstream.org/downloads/")).pack(side="left", padx=4)
        ttk.Button(buttons, text="FFmpeg配布元", command=lambda: webbrowser.open("https://ffmpeg.org/download.html")).pack(side="left", padx=4)
        ttk.Button(buttons, text="閉じる", command=window.withdraw).pack(side="left", padx=4)
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

    def _install(self, name: str) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.cancel_event = threading.Event()
        event = self.cancel_event
        self._set_setup_busy(True)

        def progress(stage: str, percent: int | None) -> None:
            self.events.put(("installer_progress", (name, stage, percent)))

        self._start_worker("install", install_tool, name, event, progress)

    def _install_all(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.cancel_event = threading.Event()
        event = self.cancel_event
        self._set_setup_busy(True)

        def install_missing() -> None:
            for name in ("vgmstream", "ffmpeg"):
                if event.is_set():
                    return
                status = check_tools(get_settings())
                if status[name][0]:
                    continue
                self.events.put(("installer_progress", (name, "導入を開始します", 0)))
                install_tool(
                    name, event,
                    lambda stage, percent, selected=name: self.events.put(
                        ("installer_progress", (selected, stage, percent))
                    ),
                )

        self._start_worker("install", install_missing)

    def _set_setup_busy(self, busy: bool) -> None:
        self.setup_busy = busy
        state = "disabled" if busy else "normal"
        if self.setup_window and self.setup_window.winfo_exists():
            for button in self.setup_actions:
                button.configure(state=state)
            if self.setup_cancel_button:
                self.setup_cancel_button.configure(state="normal" if busy else "disabled")
            if self.setup_progress:
                self.setup_progress.configure(mode="indeterminate" if busy else "determinate")
                if busy:
                    self.setup_progress.configure(value=0)
                    self.setup_progress.start(12)
                else:
                    self.setup_progress.stop()
        self.setup_button.configure(state=state)
        self.start_button.configure(state=state if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _choose_tool(self, name: str) -> None:
        executable = filedialog.askopenfilename(
            parent=self.setup_window, title="実行ファイルを選択",
            filetypes=(("Windows実行ファイル", "*.exe"), ("すべてのファイル", "*.*")),
        )
        if not executable:
            return
        try:
            self.settings = save_tool_path(name, Path(executable), self.settings)
            self._update_setup_status()
        except (SetupError, OSError) as exc:
            self._show_setup_error(exc)

    def _show_setup_error(self, error: object) -> None:
        text = f"ツールを準備できませんでした: {error}\n再試行するか、『セットアップガイド』の手動導入手順をご利用ください。"
        if self.setup_status:
            self.setup_status.configure(text=text)
        self._append_log(text)

    def _choose_zip(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.setup_window, title="ダウンロード済みツールZIPを選択",
            filetypes=(("ZIPアーカイブ", "*.zip"),),
        )
        if not path:
            return
        selected = Path(path)
        if self.worker and self.worker.is_alive():
            return
        self.cancel_event = threading.Event()
        cancel_event = self.cancel_event
        self._set_setup_busy(True)

        def install_from_zip() -> list[str]:
            from tool_setup import install_archive

            return install_archive(
                selected, cancel_event,
                lambda stage, percent: self.events.put(("installer_progress", ("zip", stage, percent))),
            )

        self._start_worker("zip_install", install_from_zip)

    def _drain_events(self) -> None:
        try:
            # Yield to Tk regularly even when a download produces many events.
            for _ in range(100):
                event, value = self.events.get_nowait()
                if event == "tool_check_done":
                    self._update_setup_status(value)
                    if not all(ready for ready, _ in self.tool_status.values()):
                        self._open_setup()
                elif event == "tool_check_error":
                    self.tool_status_text.set(f"ツール確認エラー: {value}")
                    self._open_setup()
                elif event == "conversion_progress":
                    stage, source, index, total = value
                    self.progress_bar.configure(maximum=max(total, 1), value=index if stage in ("完了", "スキップ") or stage.startswith("失敗:") else index - 1)
                    self.progress_text.set(f"{index} / {total} 曲　{stage}: {source.name}")
                    if stage.startswith("失敗:"):
                        self._append_log(f"{source.name}: {stage.removeprefix('失敗: ')}")
                    elif stage == "スキップ":
                        self._append_log(f"{source.name}: 既存の出力ファイルがあるためスキップしました。")
                elif event == "conversion_done":
                    summary = value
                    self._set_setup_busy(False)
                    self.cancel_event = None
                    self._set_conversion_controls(False)
                    if self.pending_close:
                        self.root.destroy()
                        return
                    self.result_text.set(
                        f"成功 {summary.success} ／ スキップ {summary.skipped} ／ 失敗 {summary.failed}"
                    )
                    self.progress_text.set("中止しました" if summary.cancelled else "変換が完了しました")
                    self.open_output_button.configure(state="normal" if summary.success else "disabled")
                    self._append_log(self.result_text.get())
                    if summary.failed:
                        messagebox.showwarning("変換結果", f"{summary.failed} 曲を変換できませんでした。詳細は進行状況をご確認ください。", parent=self.root)
                elif event == "conversion_error":
                    self._set_setup_busy(False)
                    self.cancel_event = None
                    self._set_conversion_controls(False)
                    messagebox.showerror("変換エラー", str(value), parent=self.root)
                elif event == "installer_progress":
                    if self.cancel_event and self.cancel_event.is_set():
                        continue
                    name, stage, percent = value
                    if self.setup_status:
                        label = {"vgmstream": "音声読み取りツール", "ffmpeg": "音声ファイル作成ツール"}.get(name, "ツールZIP")
                        suffix = f" {percent}%" if percent is not None else ""
                        self.setup_status.configure(text=f"{label}: {stage}{suffix}")
                    if self.setup_progress and percent is not None:
                        self.setup_progress.stop()
                        self.setup_progress.configure(mode="determinate", value=percent)
                elif event in ("install_done", "zip_install_done", "install_error", "zip_install_error"):
                    was_cancelled = bool(self.cancel_event and self.cancel_event.is_set())
                    self._set_setup_busy(False)
                    self.cancel_event = None
                    if self.pending_close:
                        self.root.destroy()
                        return
                    failed = event.endswith("_error")
                    self._update_setup_status(hide_when_ready=not failed and not was_cancelled)
                    if was_cancelled:
                        if self.setup_status:
                            self.setup_status.configure(text="導入を中止しました。再試行または手動導入できます。")
                    elif failed:
                        self._show_setup_error(value)
                elif event == "preview_done":
                    revision, signature, result = value
                    if revision == self.preview_revision and signature == self._selection_signature():
                        self.preview_jobs, preview = result
                        self.preview_signature = signature
                        self.preview_text.set(preview)
        except queue.Empty:
            pass
        if self.pending_close:
            if not self.worker or not self.worker.is_alive():
                self.root.destroy()
            else:
                self.root.after(80, self._drain_events)
        else:
            self.root.after(80, self._drain_events)

    def _close_request(self) -> None:
        if self.worker and self.worker.is_alive():
            self.pending_close = True
            if self.cancel_event:
                self.cancel_event.set()
            self.progress_text.set("処理を中止して終了しています…")
            self.start_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            return
        self.root.destroy()

    def _set_conversion_controls(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for control in (
            self.input_entry, self.output_entry, self.choose_file_button,
            self.choose_folder_button, self.choose_output_button, self.recursive_box,
            self.overwrite_box,
        ):
            control.configure(state=state)
        format_state = "disabled" if busy else "readonly"
        self.output_format_box.configure(state=format_state)
        audio_options_state = "disabled" if busy or self.output_format.get() != "mp3" else "readonly"
        self.quality_box.configure(state=audio_options_state)
        self.bitrate_box.configure(state=audio_options_state)
        self.details_button.configure(state="disabled" if busy or self.output_format.get() != "mp3" else "normal")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    root = tk.Tk()
    NwaApp(root).run()


if __name__ == "__main__":
    main()
