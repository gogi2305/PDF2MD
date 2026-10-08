"""Tkinter-интерфейс приложения: вкладки «Конвертация» и «Поиск по документам»."""

import os
import threading
import queue
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from .answerers import OllamaAnswerer
from .config_store import load_config, save_config
from .constants import ANSWER_PROVIDERS, DEFAULT_DOC_LANGUAGE, DOC_LANGUAGES, IMAGE_EXTENSIONS, INDEX_VEC_FILE, MARKITDOWN_EXTENSIONS, SERVICES, SERVICE_KEY_URLS
from .i18n import ANSWER_LABELS_I18N, SERVICE_LABELS_I18N, UI
from .messages import set_language, tr
from .workers import ConvertWorker, IndexWorker, SearchWorker

class _TaggedQueue:
    """Очередь для одного воркера: каждое его сообщение уходит в общую очередь
    вместе с обработчиком своей вкладки. Так сообщения не путаются, даже если
    хвост от завершившейся задачи ещё не разобран, когда стартует следующая."""

    def __init__(self, target, handler):
        self._target, self._handler = target, handler

    def put(self, item):
        self._target.put((self._handler, item))

class App:
    def __init__(self, root):
        self.root = root
        self.root.geometry("900x780")
        self.root.minsize(780, 680)

        self.config = load_config()
        self.api_keys = dict(self.config.get("api_keys", {}))
        self.msg_queue = queue.Queue()
        self.worker = None
        self.cancel_event = threading.Event()
        self._suspend_trace = False

        self.app_dir = Path(__file__).resolve().parent
        lang = self.config.get("language", "ru")
        if lang not in ("ru", "en"):
            lang = "ru"
        self.lang = lang
        set_language(lang)

        self._build_ui()
        self._tick()

    def t(self, key, **kwargs):
        """UI translation helper."""
        s = UI.get(self.lang, UI["ru"]).get(key) or UI["ru"].get(key) or key
        if kwargs:
            try:
                return s.format(**kwargs)
            except Exception:
                return s
        return s

    def _service_labels(self):
        return SERVICE_LABELS_I18N.get(self.lang, SERVICE_LABELS_I18N["ru"])

    def _answer_labels(self):
        return ANSWER_LABELS_I18N.get(self.lang, ANSWER_LABELS_I18N["ru"])

    # ---------- Общие методы ----------
    def _log(self, widget, text):
        ts = datetime.now().strftime("%H:%M:%S")
        widget.configure(state="normal")
        widget.insert("end", f"[{ts}] {text}\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _add_paste_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label=self.t("menu_paste"), command=lambda: self._paste_to(widget))
        menu.add_command(label=self.t("menu_copy"), command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label=self.t("menu_cut"), command=lambda: widget.event_generate("<<Cut>>"))
        widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _paste_to(self, widget):
        try:
            text = self.root.clipboard_get()
            widget.delete(0, tk.END)
            widget.insert(0, text.strip())
        except tk.TclError:
            pass

    def _save_cfg(self):
        self.config["api_keys"] = self.api_keys
        self.config["language"] = self.lang
        save_config(self.config)

    def _on_lang_change(self, _event=None):
        choice = self.lang_var.get()
        new_lang = "en" if choice.startswith("En") or choice == "en" else "ru"
        if new_lang == self.lang:
            return
        self.lang = new_lang
        set_language(new_lang)
        self.config["language"] = self.lang
        save_config(self.config)
        # Rebuild entire UI in the new language
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()

    # ---------- Построение UI ----------
    def _build_ui(self):
        self.root.title(self.t("title"))

        # Language selector (top bar)
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(top, text=self.t("lang")).pack(side="left")
        self.lang_var = tk.StringVar(value="Русский" if self.lang == "ru" else "English")
        lang_combo = ttk.Combobox(
            top, textvariable=self.lang_var, state="readonly", width=12,
            values=["Русский", "English"],
        )
        lang_combo.pack(side="left", padx=6)
        lang_combo.bind("<<ComboboxSelected>>", self._on_lang_change)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_convert = ttk.Frame(nb)
        self.tab_search = ttk.Frame(nb)
        nb.add(self.tab_convert, text=self.t("tab_convert"))
        nb.add(self.tab_search, text=self.t("tab_search"))
        self._build_convert_tab(self.tab_convert)
        self._build_search_tab(self.tab_search)

    # ---------- Вкладка Конвертация ----------
    def _build_convert_tab(self, parent):
        pad = {"padx": 8, "pady": 3}

        in_frame = ttk.LabelFrame(parent, text=self.t("in_frame"))
        in_frame.pack(fill="x", **pad)

        # Левая часть — список с прокруткой
        list_frame = ttk.Frame(in_frame)
        list_frame.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        self.inputs_list = tk.Listbox(list_frame, height=3, activestyle="dotbox", selectmode="extended")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.inputs_list.yview)
        self.inputs_list.configure(yscrollcommand=list_scroll.set)
        self.inputs_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")

        # Правая часть — кнопки управления списком, сетка 2×2 (компактнее по высоте)
        btn_col = ttk.Frame(in_frame)
        btn_col.pack(side="left", fill="y", padx=4, pady=4)
        ttk.Button(btn_col, text=self.t("btn_add_folder"), width=12, command=self._c_add_folder).grid(row=0, column=0, padx=2, pady=2)
        ttk.Button(btn_col, text=self.t("btn_add_files"), width=12, command=self._c_add_files).grid(row=0, column=1, padx=2, pady=2)
        ttk.Button(btn_col, text=self.t("btn_remove"), width=12, command=self._c_remove_selected).grid(row=1, column=0, padx=2, pady=2)
        ttk.Button(btn_col, text=self.t("btn_clear"), width=12, command=self._c_clear_inputs).grid(row=1, column=1, padx=2, pady=2)

        # Восстанавливаем из конфига сохранённый список (или старое одиночное поле)
        saved_list = self.config.get("last_inputs")
        if not saved_list and self.config.get("last_input"):
            saved_list = [self.config.get("last_input")]
        for p in (saved_list or []):
            if p and p.strip():
                self.inputs_list.insert("end", p)

        out_frame = ttk.LabelFrame(parent, text=self.t("out_frame"))
        out_frame.pack(fill="x", **pad)
        default_out = self.config.get("last_output", str(self.app_dir / "output"))
        self.output_var = tk.StringVar(value=default_out)
        ttk.Entry(out_frame, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=6, pady=4)
        ttk.Button(out_frame, text=self.t("btn_browse"), command=self._c_pick_output).pack(side="left", padx=3, pady=6)

        set_frame = ttk.LabelFrame(parent, text=self.t("set_frame"))
        set_frame.pack(fill="x", **pad)

        srv_row = ttk.Frame(set_frame); srv_row.pack(fill="x", padx=6, pady=2)
        ttk.Label(srv_row, text=self.t("service")).pack(side="left")
        self.service_var = tk.StringVar(value=self.config.get("service", "llamaparse"))
        self.service_combo = ttk.Combobox(
            srv_row, textvariable=self.service_var,
            values=[self._service_labels()[s] for s in SERVICES],
            state="readonly", width=44,
        )
        try: idx = SERVICES.index(self.service_var.get())
        except ValueError: idx = 0; self.service_var.set(SERVICES[0])
        self.service_combo.current(idx)
        self.service_combo.pack(side="left", padx=6)
        self.service_combo.bind("<<ComboboxSelected>>", lambda e: self._update_api_field())

        api_row = ttk.Frame(set_frame); api_row.pack(fill="x", padx=6, pady=2)
        self.api_label = ttk.Label(api_row, text=self.t("api_key"))
        self.api_label.pack(side="left")
        self.api_var = tk.StringVar()
        self.api_entry = ttk.Entry(api_row, textvariable=self.api_var, show="*", width=40)
        self.api_entry.pack(side="left", padx=6)
        self._add_paste_menu(self.api_entry)
        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(api_row, text=self.t("show"), variable=self.show_key_var,
                        command=lambda: self.api_entry.config(show="" if self.show_key_var.get() else "*")).pack(side="left")
        ttk.Button(api_row, text=self.t("get_key"), command=self._c_open_key_page).pack(side="right")
        ttk.Button(api_row, text=self.t("paste"), command=lambda: self._paste_to(self.api_entry)).pack(side="right", padx=4)

        self._update_api_field()
        self.api_var.trace_add("write", self._on_api_change)

        opt_row = ttk.Frame(set_frame); opt_row.pack(fill="x", padx=6, pady=2)
        self.scan_mode_var = tk.BooleanVar(value=self.config.get("scan_mode", True))
        ttk.Checkbutton(opt_row, text=self.t("scan_mode"),
                        variable=self.scan_mode_var).pack(side="left")
        ttk.Label(opt_row, text=self.t("doc_language")).pack(side="left")
        self.doc_lang_combo = ttk.Combobox(
            opt_row, state="readonly", width=14, values=list(DOC_LANGUAGES.values()))
        doc_codes = list(DOC_LANGUAGES)
        saved_doc_lang = self.config.get("doc_language", DEFAULT_DOC_LANGUAGE)
        self.doc_lang_combo.current(
            doc_codes.index(saved_doc_lang) if saved_doc_lang in doc_codes
            else doc_codes.index(DEFAULT_DOC_LANGUAGE))
        self.doc_lang_combo.pack(side="left", padx=6)

        opt_row_route = ttk.Frame(set_frame); opt_row_route.pack(fill="x", padx=6, pady=2)
        self.auto_route_var = tk.BooleanVar(value=self.config.get("auto_route", True))
        ttk.Checkbutton(
            opt_row_route,
            text=self.t("auto_route"),
            variable=self.auto_route_var,
        ).pack(side="left")

        opt_row_pre = ttk.Frame(set_frame); opt_row_pre.pack(fill="x", padx=6, pady=2)
        self.preprocess_var = tk.BooleanVar(value=self.config.get("preprocess_images", True))
        ttk.Checkbutton(
            opt_row_pre,
            text=self.t("preprocess"),
            variable=self.preprocess_var,
        ).pack(side="left")

        opt_row_qa = ttk.Frame(set_frame); opt_row_qa.pack(fill="x", padx=6, pady=2)
        self.assess_var = tk.BooleanVar(value=self.config.get("assess_quality", True))
        ttk.Checkbutton(
            opt_row_qa,
            text=self.t("assess"),
            variable=self.assess_var,
        ).pack(side="left")

        opt_row_cc = ttk.Frame(set_frame); opt_row_cc.pack(fill="x", padx=6, pady=2)
        ttk.Label(opt_row_cc, text=self.t("crosscheck")).pack(side="left")
        self.crosscheck_var = tk.StringVar()
        self.crosscheck_combo = ttk.Combobox(
            opt_row_cc, textvariable=self.crosscheck_var, state="readonly", width=42,
            values=[self.t("crosscheck_off")] + [self._service_labels()[s] for s in SERVICES])
        cc_saved = self.config.get("crosscheck_service", "")
        self.crosscheck_combo.current(SERVICES.index(cc_saved) + 1 if cc_saved in SERVICES else 0)
        self.crosscheck_combo.pack(side="left", padx=6)

        opt_row2 = ttk.Frame(set_frame); opt_row2.pack(fill="x", padx=6, pady=2)
        self.chunks_var = tk.BooleanVar(value=self.config.get("make_chunks", True))
        ttk.Checkbutton(opt_row2, text=self.t("make_chunks"), variable=self.chunks_var).pack(side="left")
        ttk.Label(opt_row2, text=self.t("workers")).pack(side="left")
        self.workers_var = tk.IntVar(value=self.config.get("workers", 2))
        ttk.Spinbox(opt_row2, from_=1, to=8, textvariable=self.workers_var, width=5).pack(side="left", padx=6)

        ctrl = ttk.Frame(parent); ctrl.pack(fill="x", **pad)
        self.c_start_btn = ttk.Button(ctrl, text=self.t("start"), command=self._c_start)
        self.c_start_btn.pack(side="left", padx=4)
        self.c_stop_btn = ttk.Button(ctrl, text=self.t("stop"), command=self._c_stop, state="disabled")
        self.c_stop_btn.pack(side="left", padx=4)
        ttk.Button(ctrl, text=self.t("open_output"), command=self._c_open_output).pack(side="right", padx=4)

        self.c_progress = ttk.Progressbar(parent, mode="determinate")
        self.c_progress.pack(fill="x", padx=10, pady=2)
        self.c_status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(parent, textvariable=self.c_status_var).pack(fill="x", padx=10)

        log_frame = ttk.LabelFrame(parent, text=self.t("log"))
        log_frame.pack(fill="both", expand=True, **pad)
        self.c_log = scrolledtext.ScrolledText(log_frame, height=9, wrap="word", font=("Consolas", 9))
        self.c_log.pack(fill="both", expand=True, padx=4, pady=4)
        self.c_log.configure(state="disabled")
        self._log(self.c_log, self.t("convert_intro"))
        self._log(self.c_log, tr("gui_intro_digital"))
        self._log(self.c_log, tr("gui_intro_office"))

    def _current_service(self):
        try:
            idx = self.service_combo.current()
            if 0 <= idx < len(SERVICES): return SERVICES[idx]
        except Exception: pass
        return self.service_var.get() if self.service_var.get() in SERVICES else SERVICES[0]

    def _update_api_field(self):
        svc = self._current_service()
        self._suspend_trace = True
        try: self.api_var.set(self.api_keys.get(svc, ""))
        finally: self._suspend_trace = False
        self.api_label.config(text=self.t("api_key_for", svc=svc))

    def _on_api_change(self, *args):
        if self._suspend_trace: return
        svc = self._current_service()
        self.api_keys[svc] = self.api_var.get().strip()

    def _c_add_folder(self):
        p = filedialog.askdirectory(title=self.t("pick_folder"))
        if p:
            self.inputs_list.insert("end", p)

    def _c_add_files(self):
        # Можно выбрать сразу несколько файлов
        img_pat = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
        doc_pat = " ".join(f"*{e}" for e in sorted(MARKITDOWN_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title=self.t("pick_files"),
            filetypes=[
                (tr("gui_filter_all_supported"), f"*.pdf *.zip {img_pat} {doc_pat}"),
                (tr("gui_filter_docs"), doc_pat),
                (tr("gui_filter_pdf_img"), f"*.pdf {img_pat}"),
                (tr("gui_filter_all"), "*.*"),
            ]
        )
        for p in paths:
            self.inputs_list.insert("end", p)

    def _c_remove_selected(self):
        # Удаляем сверху вниз чтобы индексы не съезжали
        for idx in sorted(self.inputs_list.curselection(), reverse=True):
            self.inputs_list.delete(idx)

    def _c_clear_inputs(self):
        self.inputs_list.delete(0, "end")

    def _get_inputs_list(self):
        return [self.inputs_list.get(i) for i in range(self.inputs_list.size())]

    def _c_pick_output(self):
        p = filedialog.askdirectory(title=self.t("pick_output"))
        if p: self.output_var.set(p)

    def _c_open_output(self):
        out = self.output_var.get()
        if out and Path(out).exists():
            try: os.startfile(out)
            except AttributeError:
                import subprocess
                subprocess.Popen(["xdg-open", out])
        else:
            messagebox.showinfo("PDF2MD", self.t("folder_missing"))

    def _c_open_key_page(self):
        import webbrowser
        url = SERVICE_KEY_URLS.get(self._current_service(), "")
        if url: webbrowser.open(url)

    def _busy(self):
        """True (и предупреждение), если уже идёт конвертация, индексация или поиск.
        Задачи делят одну кнопку отмены и одну очередь — запускаем по одной."""
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("PDF2MD", tr("gui_busy"))
            return True
        return False

    def _c_start(self):
        if self._busy(): return
        inputs = self._get_inputs_list()
        od = self.output_var.get().strip()
        svc = self._current_service()
        key = self.api_var.get().strip()
        if not inputs:
            messagebox.showerror("PDF2MD", self.t("err_no_input")); return
        # Проверяем что хотя бы один путь существует
        existing = [p for p in inputs if Path(p).exists()]
        if not existing:
            messagebox.showerror("PDF2MD", self.t("err_paths")); return
        if len(existing) < len(inputs):
            self._log(self.c_log, tr("gui_missing_paths", n=len(inputs) - len(existing)))
        if not od:
            messagebox.showerror("PDF2MD", self.t("err_no_output")); return
        if not key:
            url = SERVICE_KEY_URLS.get(svc, "")
            messagebox.showerror("PDF2MD", self.t("err_api_key", svc=svc, url=url)); return
        self.api_keys[svc] = key
        # Второй движок для сверки (часть B) — опционально
        cc_idx = self.crosscheck_combo.current()
        cc_service = SERVICES[cc_idx - 1] if cc_idx > 0 else ""
        cc_key = ""
        if cc_service:
            if cc_service == svc:
                messagebox.showerror("PDF2MD", self.t("err_crosscheck_same")); return
            cc_key = self.api_keys.get(cc_service, "").strip()
            if not cc_key:
                messagebox.showerror(
                    "PDF2MD",
                    self.t("err_crosscheck_key", svc=self._service_labels()[cc_service]))
                return
        doc_lang = list(DOC_LANGUAGES)[max(0, self.doc_lang_combo.current())]
        self.config.update({"api_keys": self.api_keys, "service": svc,
                            "last_inputs": inputs, "last_output": od,
                            "scan_mode": self.scan_mode_var.get(),
                            "doc_language": doc_lang,
                            "auto_route": self.auto_route_var.get(),
                            "preprocess_images": self.preprocess_var.get(),
                            "assess_quality": self.assess_var.get(),
                            "crosscheck_service": cc_service,
                            "make_chunks": self.chunks_var.get(),
                            "workers": self.workers_var.get()})
        # Чистим старые ключи
        self.config.pop("api_key", None)
        self.config.pop("last_input", None)
        save_config(self.config)
        opts = {"scan_mode": self.scan_mode_var.get(),
                "doc_language": doc_lang,
                "auto_route": self.auto_route_var.get(),
                "preprocess_images": self.preprocess_var.get(),
                "assess_quality": self.assess_var.get(),
                "crosscheck_service": cc_service,
                "crosscheck_key": cc_key,
                "make_chunks": self.chunks_var.get(),
                "workers": self.workers_var.get()}
        self.cancel_event.clear()
        self.worker = ConvertWorker(existing, od, svc, key, opts,
                                   _TaggedQueue(self.msg_queue, self._handle_convert_msg), self.cancel_event)
        self.worker.start()
        self.c_start_btn.config(state="disabled"); self.c_stop_btn.config(state="normal")
        self._log(self.c_log, "=" * 60)
        self._log(self.c_log, tr("gui_launch", svc=svc, n=len(existing)))

    def _c_stop(self):
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.c_status_var.set(self.t("stopping"))

    # ---------- Вкладка Поиск ----------
    def _build_search_tab(self, parent):
        pad = {"padx": 8, "pady": 3}

        # Папка с чанками
        ch_frame = ttk.LabelFrame(parent, text=self.t("chunks_frame"))
        ch_frame.pack(fill="x", **pad)
        default_chunks = self.config.get("search_chunks_dir", str(self.app_dir / "output" / "chunks"))
        self.search_chunks_var = tk.StringVar(value=default_chunks)
        ttk.Entry(ch_frame, textvariable=self.search_chunks_var).pack(side="left", fill="x", expand=True, padx=6, pady=8)
        ttk.Button(ch_frame, text=self.t("btn_browse"), command=self._s_pick_chunks).pack(side="left", padx=3, pady=6)

        # Папка индекса
        ix_frame = ttk.LabelFrame(parent, text=self.t("index_frame"))
        ix_frame.pack(fill="x", **pad)
        default_index = self.config.get("search_index_dir", str(self.app_dir / "output" / "index"))
        self.search_index_var = tk.StringVar(value=default_index)
        ttk.Entry(ix_frame, textvariable=self.search_index_var).pack(side="left", fill="x", expand=True, padx=6, pady=8)
        ttk.Button(ix_frame, text=self.t("btn_browse"), command=self._s_pick_index).pack(side="left", padx=3, pady=6)
        ttk.Button(ix_frame, text=self.t("btn_index"), command=self._s_index).pack(side="left", padx=3, pady=6)

        # Провайдер ответа
        prov_frame = ttk.LabelFrame(parent, text=self.t("provider_frame"))
        prov_frame.pack(fill="x", **pad)

        prow = ttk.Frame(prov_frame); prow.pack(fill="x", padx=6, pady=2)
        ttk.Label(prow, text=self.t("provider")).pack(side="left")
        self.provider_var = tk.StringVar(value=self.config.get("answer_provider", "gemini"))
        self.provider_combo = ttk.Combobox(
            prow, textvariable=self.provider_var,
            values=[self._answer_labels()[p] for p in ANSWER_PROVIDERS],
            state="readonly", width=40,
        )
        try: pidx = ANSWER_PROVIDERS.index(self.provider_var.get())
        except ValueError: pidx = 0; self.provider_var.set(ANSWER_PROVIDERS[0])
        self.provider_combo.current(pidx)
        self.provider_combo.pack(side="left", padx=6)
        self.provider_combo.bind("<<ComboboxSelected>>", lambda e: self._update_provider_ui())

        # Поля для Ollama
        ollama_row = ttk.Frame(prov_frame); ollama_row.pack(fill="x", padx=6, pady=2)
        ttk.Label(ollama_row, text=self.t("ollama_model")).pack(side="left")
        self.ollama_model_var = tk.StringVar(value=self.config.get("ollama_model", "llama3.2"))
        ttk.Entry(ollama_row, textvariable=self.ollama_model_var, width=22).pack(side="left", padx=4)
        ttk.Label(ollama_row, text=self.t("ollama_url")).pack(side="left", padx=(10, 0))
        self.ollama_url_var = tk.StringVar(value=self.config.get("ollama_url", "http://localhost:11434"))
        ttk.Entry(ollama_row, textvariable=self.ollama_url_var, width=28).pack(side="left", padx=4)
        ttk.Button(ollama_row, text=self.t("check_ollama"), command=self._s_check_ollama).pack(side="left", padx=6)

        # Вопрос
        q_frame = ttk.LabelFrame(parent, text=self.t("question_frame"))
        q_frame.pack(fill="x", **pad)
        self.question_var = tk.StringVar()
        q_entry = ttk.Entry(q_frame, textvariable=self.question_var)
        q_entry.pack(side="left", fill="x", expand=True, padx=6, pady=8)
        self._add_paste_menu(q_entry)
        ttk.Label(q_frame, text=self.t("topk")).pack(side="left")
        self.topk_var = tk.IntVar(value=int(self.config.get("top_k", 5)))
        ttk.Spinbox(q_frame, from_=1, to=20, textvariable=self.topk_var, width=4).pack(side="left", padx=4)
        ttk.Button(q_frame, text=self.t("ask"), command=self._s_ask).pack(side="left", padx=6, pady=6)

        self.s_status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(parent, textvariable=self.s_status_var).pack(fill="x", padx=10)

        # Окно ответа
        ans_frame = ttk.LabelFrame(parent, text=self.t("answer_frame"))
        ans_frame.pack(fill="both", expand=True, **pad)
        self.s_answer = scrolledtext.ScrolledText(ans_frame, height=10, wrap="word", font=("Segoe UI", 10))
        self.s_answer.pack(fill="both", expand=True, padx=4, pady=4)

        # Источники
        src_frame = ttk.LabelFrame(parent, text=self.t("sources_frame"))
        src_frame.pack(fill="both", expand=True, **pad)
        self.s_sources = scrolledtext.ScrolledText(src_frame, height=6, wrap="word", font=("Consolas", 9))
        self.s_sources.pack(fill="both", expand=True, padx=4, pady=4)

        # Лог поиска
        log_frame = ttk.LabelFrame(parent, text=self.t("log"))
        log_frame.pack(fill="x", **pad)
        self.s_log = scrolledtext.ScrolledText(log_frame, height=5, wrap="word", font=("Consolas", 9))
        self.s_log.pack(fill="both", expand=True, padx=4, pady=4)
        self.s_log.configure(state="disabled")

        self._update_provider_ui()
        self._log(self.s_log, self.t("search_intro"))
        self._log(self.s_log, tr("gui_intro_embed"))

    def _current_provider(self):
        try:
            idx = self.provider_combo.current()
            if 0 <= idx < len(ANSWER_PROVIDERS): return ANSWER_PROVIDERS[idx]
        except Exception: pass
        return self.provider_var.get() if self.provider_var.get() in ANSWER_PROVIDERS else ANSWER_PROVIDERS[0]

    def _update_provider_ui(self):
        # ничего не скрываем — оба поля могут быть полезны
        pass

    def _s_pick_chunks(self):
        p = filedialog.askdirectory(title=self.t("pick_chunks"))
        if p: self.search_chunks_var.set(p)

    def _s_pick_index(self):
        p = filedialog.askdirectory(title=self.t("pick_index"))
        if p: self.search_index_var.set(p)

    def _s_check_ollama(self):
        oa = OllamaAnswerer(model=self.ollama_model_var.get(), url=self.ollama_url_var.get())
        if oa.check():
            messagebox.showinfo("Ollama", tr("gui_ollama_ok", url=oa.url))
        else:
            messagebox.showwarning(
                "Ollama",
                tr("gui_ollama_down", url=oa.url, model=self.ollama_model_var.get())
            )

    def _s_index(self):
        if self._busy(): return
        chunks_dir = self.search_chunks_var.get().strip()
        index_dir = self.search_index_var.get().strip()
        if not chunks_dir or not Path(chunks_dir).exists():
            messagebox.showerror("PDF2MD", self.t("err_chunks_missing")); return
        if not index_dir:
            messagebox.showerror("PDF2MD", self.t("err_index_folder")); return
        api_key = self.api_keys.get("gemini", "")
        if not api_key:
            messagebox.showerror("PDF2MD", self.t("err_embed_key")); return
        # Сохраняем настройки
        self.config["search_chunks_dir"] = chunks_dir
        self.config["search_index_dir"] = index_dir
        save_config(self.config)

        self.cancel_event.clear()
        self.worker = IndexWorker(chunks_dir, index_dir, api_key,
                                  _TaggedQueue(self.msg_queue, self._handle_index_msg), self.cancel_event)
        self.worker.start()
        self._log(self.s_log, "=" * 60)
        self._log(self.s_log, tr("gui_indexing", src=chunks_dir, dst=index_dir))

    def _s_ask(self):
        if self._busy(): return
        question = self.question_var.get().strip()
        if not question:
            messagebox.showerror("PDF2MD", self.t("err_no_question")); return
        index_dir = self.search_index_var.get().strip()
        if not index_dir or not (Path(index_dir) / INDEX_VEC_FILE).exists():
            messagebox.showerror("PDF2MD", self.t("err_no_index")); return
        embed_key = self.api_keys.get("gemini", "")
        if not embed_key:
            messagebox.showerror("PDF2MD", self.t("err_embed_query")); return
        provider = self._current_provider()
        if provider == "gemini":
            if not self.api_keys.get("gemini"):
                messagebox.showerror("PDF2MD", self.t("err_gemini_answer")); return
            cfg = {"api_key": self.api_keys.get("gemini")}
        else:
            cfg = {"model": self.ollama_model_var.get().strip() or "llama3.2",
                   "url": self.ollama_url_var.get().strip() or "http://localhost:11434"}

        self.config["answer_provider"] = provider
        self.config["ollama_model"] = self.ollama_model_var.get()
        self.config["ollama_url"] = self.ollama_url_var.get()
        self.config["top_k"] = int(self.topk_var.get())
        save_config(self.config)

        # Чистим окна
        self.s_answer.delete("1.0", "end")
        self.s_sources.delete("1.0", "end")

        self.cancel_event.clear()
        self.worker = SearchWorker(
            question, index_dir, embed_key, provider, cfg,
            int(self.topk_var.get()), _TaggedQueue(self.msg_queue, self._handle_search_msg), self.cancel_event
        )
        self.worker.start()
        self._log(self.s_log, "=" * 60)
        self._log(self.s_log, tr("gui_question", q=question))

    # ---------- Опрос очереди сообщений ----------
    def _tick(self):
        try:
            while True:
                handler, (kind, payload) = self.msg_queue.get_nowait()
                handler(kind, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._tick)

    def _handle_convert_msg(self, kind, payload):
        if kind == "log": self._log(self.c_log, payload)
        elif kind == "status": self.c_status_var.set(payload)
        elif kind == "progress":
            cur, tot = payload
            if tot > 0:
                self.c_progress["maximum"] = tot; self.c_progress["value"] = cur
        elif kind == "error":
            self._log(self.c_log, tr("gui_error_log", msg=payload))
            self.c_status_var.set(tr("gui_error_status"))
            self.c_start_btn.config(state="normal"); self.c_stop_btn.config(state="disabled")
            messagebox.showerror("PDF2MD", payload[:500])
        elif kind == "done":
            s = payload
            self.c_status_var.set(tr("gui_convert_done_status", processed=s["processed"],
                                     skipped=s["skipped"], errors=len(s["errors"])))
            self._log(self.c_log, "=" * 60)
            self._log(self.c_log, tr("gui_convert_summary", total=s["total"], processed=s["processed"],
                                     skipped=s["skipped"], errors=len(s["errors"])))
            for e in s["errors"][:10]:
                self._log(self.c_log, f"  - {e}")
            q = s.get("quality")
            if q:
                self._log(self.c_log, tr("gui_quality_summary", reliable=q["reliable"],
                                         review=q["review"], suspicious=q["suspicious"]))
            pg = s.get("pages")
            if pg:
                self._log(self.c_log, tr("gui_pages_summary", ok=pg["ok"], problem=pg["problem"],
                                         unverified=pg["unverified"]))
            cc = s.get("crosscheck")
            if cc:
                self._log(self.c_log, tr("gui_cc_summary", svc=cc["service"], checked=cc["checked"],
                                         agree=cc["agree"], disagree=cc["disagree"]))
            self.c_start_btn.config(state="normal"); self.c_stop_btn.config(state="disabled")
            if s.get("quota_stop"):
                self.c_status_var.set(tr("gui_quota_status"))
                messagebox.showwarning(tr("gui_quota_title"), s["quota_stop"])

    def _handle_index_msg(self, kind, payload):
        if kind == "log": self._log(self.s_log, payload)
        elif kind == "status": self.s_status_var.set(payload)
        elif kind == "progress":
            cur, tot = payload
            self.s_status_var.set(tr("gui_index_progress", cur=cur, tot=tot))
        elif kind == "error":
            self._log(self.s_log, tr("gui_error_log", msg=payload))
            self.s_status_var.set(tr("gui_error_status"))
            messagebox.showerror("PDF2MD", payload[:500])
        elif kind == "done":
            s = payload
            self.s_status_var.set(tr("gui_index_status", added=s["added"], total=s["total"]))
            self._log(self.s_log, tr("gui_index_done_log", summary=s))
            messagebox.showinfo("PDF2MD", tr("gui_index_done_box", added=s["added"]))

    def _handle_search_msg(self, kind, payload):
        if kind == "log": self._log(self.s_log, payload)
        elif kind == "status": self.s_status_var.set(payload)
        elif kind == "error":
            self._log(self.s_log, tr("gui_error_log", msg=payload))
            self.s_status_var.set(tr("gui_error_status"))
            messagebox.showerror("PDF2MD", payload[:500])
        elif kind == "answer":
            text, sources = payload
            self.s_answer.delete("1.0", "end")
            self.s_answer.insert("end", text)
            self.s_sources.delete("1.0", "end")
            for s in sources:
                self.s_sources.insert("end",
                    f"[score={s['score']:.3f}] {s['source']}\n  {s['snippet']}\n\n")
            self.s_status_var.set(tr("gui_done"))
            self._log(self.s_log, tr("gui_answer_received"))

def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        themes = style.theme_names()
        if "vista" in themes: style.theme_use("vista")
        elif "clam" in themes: style.theme_use("clam")
    except Exception: pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
