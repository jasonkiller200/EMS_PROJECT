# ems_project/data_collector.py

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
import requests
import datetime
import json
import threading
import time
import pandas as pd
from openpyxl.drawing.image import Image as OpenpyxlImage
import io
import calendar
import ctypes
import os

# --- 函式庫可用性檢查 ---
try:
    import matplotlib
    matplotlib.use("TkAgg")
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei']
    matplotlib.rcParams['axes.unicode_minus'] = False
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    from tkcalendar import DateEntry
    TKCALENDAR_AVAILABLE = True
except ImportError:
    TKCALENDAR_AVAILABLE = False

# --- 全域設定 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "url_manager.db"
DB_PATH = os.path.join(BASE_DIR, DB_NAME)

# --- 資料庫初始化與遷移 ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 原有表格
    c.execute('''CREATE TABLE IF NOT EXISTS url_list (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS data_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, template_name TEXT NOT NULL UNIQUE, description TEXT, columns_config TEXT NOT NULL, unique_key_column TEXT, last_run_time TEXT)''')
    
    # ISO 50001 相關表格
    # 1. 儲存迴歸基線的主體資訊 (公式)
    c.execute('''
        CREATE TABLE IF NOT EXISTS RegressionBaselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,          -- 例如: 114年度 全廠用電基線
            year INTEGER NOT NULL,              -- 基線對應的年度
            formula_intercept REAL NOT NULL,    -- 公式的常數項 (截距)
            formula_r2 REAL,                    -- R 平方值
            notes TEXT,                         -- 備註事項
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. 儲存迴歸公式的因子係數
    c.execute('''
        CREATE TABLE IF NOT EXISTS RegressionFactors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_id INTEGER NOT NULL,
            factor_name TEXT NOT NULL,          -- 因子名稱 (例如: 工時, 外氣溫度)
            coefficient REAL NOT NULL,          -- 係數
            FOREIGN KEY (baseline_id) REFERENCES RegressionBaselines (id) ON DELETE CASCADE
        )
    ''')

    # 3. 儲存每個月的實際監測數據 (人工輸入)
    c.execute('''
        CREATE TABLE IF NOT EXISTS MonitoredData (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_id INTEGER NOT NULL,
            month INTEGER NOT NULL,             -- 1 到 12
            -- 使用 JSON 儲存所有因子數據, 例如: {"工時": 37808, "外氣溫度": 16}
            factors_json TEXT NOT NULL,         
            actual_consumption REAL,            -- 實際能源消耗量
            UNIQUE (baseline_id, month),
            FOREIGN KEY (baseline_id) REFERENCES RegressionBaselines (id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()

# --- URL 管理函式 ---
def get_urls():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT id, url, description FROM url_list ORDER BY description")
    urls = c.fetchall(); conn.close(); return urls

def add_url(url, description):
    if not url: return False, "URL不能為空"
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try: c.execute("INSERT INTO url_list (url, description) VALUES (?, ?)", (url, description)); conn.commit(); return True, "URL 已新增"
    except sqlite3.IntegrityError: return False, "此 URL 已存在"
    finally: conn.close()

def delete_url(url_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("DELETE FROM url_list WHERE id = ?", (url_id,)); conn.commit(); conn.close()

def update_url(url_id, url, description):
    if not url: return False, "URL不能為空"
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try: c.execute("UPDATE url_list SET url = ?, description = ? WHERE id = ?", (url, description, url_id)); conn.commit(); return True, "URL 已更新"
    except sqlite3.IntegrityError: return False, "此 URL 已存在於另一筆記錄中"
    except Exception as e: conn.rollback(); return False, f"更新時發生錯誤: {e}"
    finally: conn.close()

# --- 資料範本 (核心功能) ---
def get_templates():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT id, template_name, description, unique_key_column, last_run_time FROM data_templates")
    templates = c.fetchall(); conn.close(); return templates

def get_template_details(template_id):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM data_templates WHERE id = ?", (template_id,))
    template = c.fetchone(); conn.close(); return template

def save_template(template_id, name, desc, columns_config, unique_key):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); config_json = json.dumps(columns_config, ensure_ascii=False)
    if template_id: c.execute("UPDATE data_templates SET template_name=?, description=?, columns_config=?, unique_key_column=? WHERE id=?", (name, desc, config_json, unique_key, template_id))
    else: c.execute("INSERT INTO data_templates (template_name, description, columns_config, unique_key_column) VALUES (?, ?, ?, ?)", (name, desc, config_json, unique_key))
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        if not c.fetchone():
            col_defs = ", ".join([f'"{col["name"]}" TEXT' for col in columns_config if col['type'] != '設備狀態監控'])
            c.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})')
        else:
            c.execute(f'PRAGMA table_info("{name}")')
            existing_cols = [row[1] for row in c.fetchall()]
            for col_def in columns_config:
                if col_def["type"] == '設備狀態監控': continue
                if col_def["name"] not in existing_cols: c.execute(f'ALTER TABLE "{name}" ADD COLUMN "{col_def["name"]}" TEXT')
        conn.commit(); return True, "範本已儲存，資料表結構已同步。"
    except Exception as e: conn.rollback(); return False, f"儲存範本時發生錯誤: {e}"
    finally: conn.close()

def delete_template(template_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("SELECT template_name FROM data_templates WHERE id = ?", (template_id,)); result = c.fetchone()
    if result: c.execute("DELETE FROM data_templates WHERE id = ?", (template_id,)); c.execute(f'DROP TABLE IF EXISTS "{result[0]}"'); conn.commit()
    conn.close()

def _execute_db_function(c, function_call, table_name):
    try:
        func_name, rest = function_call.split('(', 1); params_str = rest.rsplit(')', 1)[0]; params = eval(f"({params_str})")
        if not isinstance(params, tuple): params = (params,)
    except Exception as e: return f"公式語法錯誤: {e}"
    try:
        if func_name.strip() == 'get_diff':
            if len(params) != 2: return "get_diff需要2個參數('欄位名', 行數)"
            target_column, offset = params
            if not isinstance(target_column, str) or not target_column.isidentifier(): return "無效的欄位名稱"
            if not isinstance(offset, int) or offset < 1: return "行數偏移量必須是正整數"
            limit = offset + 1; query = f'SELECT "{target_column}" FROM "{table_name}" ORDER BY id DESC LIMIT {limit}'; c.execute(query); rows = c.fetchall()
            if len(rows) < limit: return "0.00"
            try: latest_value = float(rows[0][0]); previous_value = float(rows[offset][0]); diff = latest_value - previous_value; return f"{diff:+.2f}"
            except (ValueError, TypeError, IndexError): return "非數值或資料不足"
        else: return f"未知的資料庫函式: {func_name}"
    except Exception as e: return f"公式執行錯誤: {e}"

def run_template(template_id, url_map):
    template_details = get_template_details(template_id)
    if not template_details: return False, f"找不到範本 ID: {template_id}"
    table_name = template_details['template_name']; columns_config = json.loads(template_details['columns_config']); monitor_config = next((col for col in columns_config if col['type'] == '設備狀態監控'), None)
    if monitor_config: return run_monitor_logic(template_id, table_name, monitor_config, url_map)
    else: return run_standard_logic(template_id, table_name, columns_config, template_details['unique_key_column'], url_map)

def run_monitor_logic(template_id, table_name, config, url_map):
    try:
        params = config['value']; url_id = params['url_id']; device_id = params['device_id']; on_val = params['on_val']; off_val = params['off_val']; url, _ = url_map.get(int(url_id), (None, None))
        if not url: return False, f"監控範本 '{table_name}' 中找不到 URL ID: {url_id}"
    except (KeyError, ValueError) as e: return False, f"監控範本 '{table_name}' 的設定不完整或格式錯誤: {e}"
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    try:
        try: resp = requests.get(url, timeout=10); resp.raise_for_status(); current_status = resp.text.strip()
        except Exception as e: return True, f"範本 '{table_name}' (監控模式) URL抓取失敗: {e}"
        c.execute(f'SELECT id, end_time FROM "{table_name}" WHERE device_id = ? ORDER BY id DESC LIMIT 1', (device_id,)); last_log = c.fetchone()
        is_running = (last_log is not None and last_log['end_time'] is None); now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"); log_message = f"範本 '{table_name}' (監控模式) 狀態未變化或無效，無操作。"
        if current_status == on_val and not is_running: c.execute(f'INSERT INTO "{table_name}" (device_id, start_time) VALUES (?, ?)', (device_id, now_str)); log_message = f"偵測到設備 '{device_id}' 開機，已新增紀錄。"
        elif current_status == off_val and is_running:
            c.execute(f'PRAGMA table_info("{table_name}")'); columns_info = c.fetchall(); has_duration_col = any(col['name'] == 'duration_seconds' for col in columns_info)
            if has_duration_col: c.execute(f"""UPDATE "{table_name}" SET end_time = ?, duration_seconds = CAST(strftime('%s', ?) - strftime('%s', start_time) AS INTEGER) WHERE id = ?""", (now_str, now_str, last_log['id']))
            else: c.execute(f'UPDATE "{table_name}" SET end_time = ? WHERE id = ?', (now_str, last_log['id']))
            log_message = f"偵測到設備 '{device_id}' 關機，已更新紀錄。"
        c.execute("UPDATE data_templates SET last_run_time = ? WHERE id = ?", (now_str, template_id)); conn.commit(); return True, log_message
    except sqlite3.OperationalError as e: 
        conn.rollback()
        if "no such column" in str(e): 
            return False, f"執行監控範本 '{table_name}' 失敗！\n錯誤: {e}\n\n請檢查資料表是否包含 'device_id', 'start_time', 'end_time' 等必要欄位。"
        return False, f"執行監控範本 '{table_name}' 時資料庫出錯: {e}"
    except Exception as e: 
        conn.rollback()
        return False, f"執行監控範本 '{table_name}' 時發生未知錯誤: {e}"
    finally: 
        conn.close()

def run_standard_logic(template_id, table_name, columns_config, unique_key, url_map):
    data_row = {}; deferred_db_evals = []
    for col_def in columns_config:
        col_name, source_type, source_value = col_def["name"], col_def["type"], col_def["value"]
        if source_type == "動態公式" and source_value.lower().startswith("db_eval:"): deferred_db_evals.append({'column': col_name, 'formula': source_value}); data_row[col_name] = None; continue
        if source_type == "URL":
            try:
                url_id = int(source_value)
                url, _ = url_map.get(url_id, (None, None))
                if not url:
                    return False, f"在範本 '{table_name}' 中找不到 URL ID: {url_id}"
                resp = requests.get(url, timeout=15)
                resp.raise_for_status()
                data_row[col_name] = resp.text
            except Exception as e:
                return False, f"在範本 '{table_name}' 中抓取URL失敗 ({url}): {e}"
        elif source_type == "靜態值": data_row[col_name] = source_value
        elif source_type == "動態公式":
            if source_value.lower() == "now": data_row[col_name] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif source_value.lower().startswith("eval:"):
                try: data_row[col_name] = str(eval(source_value[5:]))
                except Exception as e: data_row[col_name] = f"公式錯誤: {e}"
            else: data_row[col_name] = source_value
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        row_id, existing_id = None, None; result = None
        if unique_key and unique_key in data_row and data_row[unique_key] is not None: c.execute(f'SELECT id FROM "{table_name}" WHERE "{unique_key}" = ?', (data_row[unique_key],)); result = c.fetchone()
        if result: existing_id = result[0]
        if existing_id is not None: row_id = existing_id; set_clauses = ", ".join([f'"{k}" = ?' for k in data_row]); c.execute(f'UPDATE "{table_name}" SET {set_clauses} WHERE id = ?', tuple(list(data_row.values()) + [row_id]))
        else: cols = ", ".join([f'"{k}"' for k in data_row.keys()]); placeholders = ", ".join(["?"] * len(data_row)); c.execute(f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})', tuple(data_row.values())); row_id = c.lastrowid
        if deferred_db_evals and row_id is not None:
            update_payload = {}
            for task in deferred_db_evals: formula_full = task['formula']; function_call = formula_full[8:].strip(); result = _execute_db_function(c, function_call, table_name); update_payload[task['column']] = result
            if update_payload: set_clauses = ", ".join([f'"{k}" = ?' for k in update_payload.keys()]); c.execute(f'UPDATE "{table_name}" SET {set_clauses} WHERE id = ?', tuple(list(update_payload.values()) + [row_id]))
        c.execute("UPDATE data_templates SET last_run_time = ? WHERE id = ?", (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), template_id)); conn.commit(); return True, f"範本 '{table_name}' 執行成功。"
    except Exception as e: conn.rollback(); return False, f"執行範本 '{table_name}' 時資料庫出錯: {e}"
    finally: conn.close()

def get_table_names():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"); tables = [row[0] for row in c.fetchall()]; conn.close(); return tables
def get_table_data(table_name):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    try: c.execute(f'PRAGMA table_info("{table_name}")'); columns = [row['name'] for row in c.fetchall()]; c.execute(f'SELECT * FROM "{table_name}"'); rows = c.fetchall(); return columns, rows
    except sqlite3.OperationalError: return [], []
    finally: conn.close()
def clear_table_data(table_name):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        if not table_name.isidentifier(): return False, "無效的資料表名稱"
        c.execute(f'DELETE FROM "{table_name}"'); c.execute(f"DELETE FROM sqlite_sequence WHERE name='{table_name}'"); conn.commit(); return True, f"資料表 '{table_name}' 的內容已清空。"
    except Exception as e: conn.rollback(); return False, f"清空資料表 '{table_name}' 失敗: {e}"
    finally: conn.close()

class UrlManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent); self.title("URL 管理器"); self.geometry("600x450"); self.transient(parent); self.editing_id = None; self.setup_widgets(); self.refresh_url_list(); self.tree.bind("<Double-1>", self.on_item_double_click); self.protocol("WM_DELETE_WINDOW", self.destroy); self.grab_set(); self.wait_window(self)
    def setup_widgets(self):
        list_frame = ttk.LabelFrame(self, text="已儲存的 URL (雙擊項目以編輯)"); list_frame.pack(padx=10, pady=10, fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=("id", "desc", "url"), show="headings"); self.tree.heading("id", text="ID"); self.tree.heading("desc", text="說明"); self.tree.heading("url", text="URL"); self.tree.column("id", width=40, anchor="center"); self.tree.column("desc", width=150); self.tree.column("url", width=350); self.tree.pack(side="left", fill="both", expand=True)
        add_frame = ttk.LabelFrame(self, text="新增 / 編輯"); add_frame.pack(padx=10, pady=5, fill="x"); ttk.Label(add_frame, text="URL:").grid(row=0, column=0, padx=5, pady=5, sticky="w"); self.ent_url = ttk.Entry(add_frame, width=40); self.ent_url.grid(row=0, column=1, padx=5, pady=5, sticky="ew"); ttk.Label(add_frame, text="說明:").grid(row=1, column=0, padx=5, pady=5, sticky="w"); self.ent_desc = ttk.Entry(add_frame, width=40); self.ent_desc.grid(row=1, column=1, padx=5, pady=5, sticky="ew"); add_frame.columnconfigure(1, weight=1)
        btn_frame = ttk.Frame(self); btn_frame.pack(pady=10); self.btn_save = ttk.Button(btn_frame, text="新增", command=self.on_save); self.btn_save.pack(side="left", padx=5); ttk.Button(btn_frame, text="清除/取消編輯", command=self.clear_form).pack(side="left", padx=5); ttk.Button(btn_frame, text="刪除選取", command=self.on_delete_url).pack(side="left", padx=5); ttk.Button(btn_frame, text="關閉", command=self.destroy).pack(side="right", padx=5)
    def refresh_url_list(self): self.tree.delete(*self.tree.get_children()); [self.tree.insert("", "end", iid=r['id'], values=(r['id'], r['description'] or "", r['url'])) for r in get_urls()]
    def on_item_double_click(self, event):
        selected_item = self.tree.selection();
        if not selected_item: return
        item_id = selected_item[0]; values = self.tree.item(item_id, "values"); self.editing_id = values[0]; self.ent_url.delete(0, "end"); self.ent_desc.delete(0, "end"); self.ent_url.insert(0, values[2]); self.ent_desc.insert(0, values[1]); self.btn_save.config(text="儲存變更"); self.ent_url.focus_set()
    def on_save(self):
        url, desc = self.ent_url.get().strip(), self.ent_desc.get().strip()
        if not url: messagebox.showerror("錯誤", "URL 欄位不能為空", parent=self); return
        ok, msg = update_url(self.editing_id, url, desc) if self.editing_id is not None else add_url(url, desc)
        if ok: messagebox.showinfo("成功", msg, parent=self); self.clear_form(); self.refresh_url_list()
        else: messagebox.showerror("失敗", msg, parent=self)
    def clear_form(self): self.ent_url.delete(0, "end"); self.ent_desc.delete(0, "end"); self.editing_id = None; self.btn_save.config(text="新增"); self.ent_url.focus_set()
    def on_delete_url(self):
        selected_item = self.tree.selection()
        if not selected_item: messagebox.showwarning("警告", "請先在列表中選擇一個要刪除的 URL", parent=self); return
        if self.editing_id and self.editing_id == selected_item[0]: self.clear_form()
        url_id, url_desc = selected_item[0], self.tree.item(selected_item[0], "values")[1]
        if messagebox.askyesno("確認刪除", f"確定要刪除 '{url_desc}' 嗎？\n使用此 URL 的範本將會出錯！", parent=self): delete_url(url_id); self.refresh_url_list()

class TemplateEditor(tk.Toplevel):
    def __init__(self, parent_window, app_instance, template_id=None):
        super().__init__(parent_window); self.transient(parent_window); self.app_instance = app_instance; self.template_id = template_id; self.all_urls = get_urls(); self.url_map = {r['id']: (r['url'], r['description']) for r in self.all_urls}; self.url_display_map = {f"{r['description'] or '無說明'} ({r['url']})": r['id'] for r in self.all_urls}; self.url_display_list = sorted(list(self.url_display_map.keys())); self.title("編輯資料範本"); self.geometry("600x500"); self.columns_data = []; self.setup_widgets();
        if self.template_id: self.load_template_data()
        self.grab_set(); self.protocol("WM_DELETE_WINDOW", self.destroy); self.wait_window(self)
    def setup_widgets(self):
        frm_info = ttk.LabelFrame(self, text="基本資訊"); frm_info.pack(padx=10, pady=10, fill="x"); ttk.Label(frm_info, text="範本/資料表名稱:").grid(row=0, column=0, padx=5, pady=5, sticky="w"); self.ent_name = ttk.Entry(frm_info, width=30); self.ent_name.grid(row=0, column=1, padx=5, pady=5, sticky="ew"); ttk.Label(frm_info, text="說明:").grid(row=1, column=0, padx=5, pady=5, sticky="w"); self.ent_desc = ttk.Entry(frm_info, width=50); self.ent_desc.grid(row=1, column=1, padx=5, pady=5, sticky="ew"); ttk.Label(frm_info, text="唯一鍵 (用於更新):").grid(row=2, column=0, padx=5, pady=5, sticky="w"); self.cmb_unique_key = ttk.Combobox(frm_info, state="readonly"); self.cmb_unique_key.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        frm_cols = ttk.LabelFrame(self, text="欄位定義 (雙擊可編輯)"); frm_cols.pack(padx=10, pady=5, fill="both", expand=True); self.tree = ttk.Treeview(frm_cols, columns=("name", "type", "value"), show="headings"); self.tree.heading("name", text="欄位名稱"); self.tree.heading("type", text="資料來源類型"); self.tree.heading("value", text="來源/內容"); self.tree.column("name", width=120); self.tree.column("type", width=100); self.pack_propagate(False); self.tree.pack(side="left", fill="both", expand=True); self.tree.bind("<Double-1>", self.on_double_click_column)
        frm_col_btns = ttk.Frame(frm_cols); frm_col_btns.pack(side="left", fill="y", padx=5); ttk.Button(frm_col_btns, text="新增欄位", command=self.add_column).pack(pady=2); ttk.Button(frm_col_btns, text="刪除選取", command=self.delete_column).pack(pady=2)
        frm_main_btns = ttk.Frame(self); frm_main_btns.pack(pady=10); ttk.Button(frm_main_btns, text="儲存範本", command=self.save).pack(side="left", padx=10); ttk.Button(frm_main_btns, text="取消", command=self.destroy).pack(side="left", padx=10)
    def load_template_data(self):
        details = get_template_details(self.template_id); self.ent_name.insert(0, details['template_name'])
        if details['description']: self.ent_desc.insert(0, details['description'])
        self.columns_data = json.loads(details['columns_config']); self.refresh_treeview()
        if details['unique_key_column']: self.cmb_unique_key.set(details['unique_key_column'])
    def refresh_treeview(self):
        self.tree.delete(*self.tree.get_children()); col_names = []
        for i, col in enumerate(self.columns_data):
            display_value = col['value']
            if col['type'] == 'URL':
                try: uid = int(col['value']); url, desc = self.url_map.get(uid, ('unknown_url', '')); display_value = f"{desc or '無說明'} ({url})"
                except (ValueError, TypeError): display_value = "無效的URL ID"
            elif col['type'] == '設備狀態監控':
                try: params = col['value']; uid = int(params['url_id']); _, desc = self.url_map.get(uid, ('', '')); display_value = f"監控 '{params['device_id']}' (URL: {desc})"
                except Exception: display_value = "監控設定無效"
            if col['type'] != '設備狀態監控': col_names.append(col['name'])
            self.tree.insert("", "end", iid=i, values=(col['name'], col['type'], display_value))
        self.cmb_unique_key['values'] = [""] + col_names
    def add_column(self):
        dlg = ColumnDialog(self, title="新增欄位", url_list=self.url_display_list, editor_parent=self)
        if dlg.result: self.columns_data.append(dlg.result); self.refresh_treeview()
    def edit_column(self, index, initial_data):
        dlg = ColumnDialog(self, title="編輯欄位", url_list=self.url_display_list, editor_parent=self, initial_data=initial_data)
        if dlg.result: self.columns_data[index] = dlg.result; self.refresh_treeview()
    def on_double_click_column(self, event):
        item_iid = self.tree.identify_row(event.y)
        if not item_iid: return
        try: item_index = int(item_iid); initial_data = self.columns_data[item_index]; self.edit_column(item_index, initial_data)
        except (ValueError, IndexError): pass
    def delete_column(self):
        selected_item = self.tree.selection();
        if not selected_item: messagebox.showwarning("警告", "請選擇要刪除的欄位", parent=self); return
        try: del self.columns_data[int(selected_item[0])]; self.refresh_treeview()
        except (ValueError, IndexError): messagebox.showerror("錯誤", "無法刪除選取的項目，請重試", parent=self)
    def save(self):
        name, desc, unique_key = self.ent_name.get().strip(), self.ent_desc.get().strip(), self.cmb_unique_key.get().strip()
        if not name or not name.isidentifier(): messagebox.showerror("錯誤", "範本名稱不正確，只能包含字母、數字和底線，且不能以數字開頭。", parent=self); return
        if not self.columns_data: messagebox.showerror("錯誤", "至少需要定義一個欄位", parent=self); return
        if len([c for c in self.columns_data if c['type'] == '設備狀態監控']) > 1: messagebox.showerror("錯誤", "一個範本中最多只能定義一個 '設備狀態監控' 欄位。", parent=self); return
        if not self.template_id and any(t['template_name'].lower() == name.lower() for t in get_templates()): messagebox.showerror("錯誤", f"範本名稱 '{name}' 已存在", parent=self); return
        ok, msg = save_template(self.template_id, name, desc, self.columns_data, unique_key)
        if ok: messagebox.showinfo("成功", msg, parent=self); self.app_instance.refresh_all(); self.destroy()
        else: messagebox.showerror("失敗", msg, parent=self)

class ColumnDialog(simpledialog.Dialog):
    def __init__(self, parent, title, url_list, editor_parent, initial_data=None):
        self.url_list = url_list; self.editor_parent = editor_parent; self.url_display_map = parent.url_display_map; self.initial_data = initial_data; super().__init__(parent, title)
    def body(self, master):
        self.result = None; ttk.Label(master, text="欄位名稱:").grid(row=0, sticky="w", padx=5, pady=2); self.ent_name = ttk.Entry(master, width=40); self.ent_name.grid(row=0, column=1, pady=2); ttk.Label(master, text="資料來源類型:").grid(row=1, sticky="w", padx=5, pady=2); self.cmb_type = ttk.Combobox(master, values=["URL", "靜態值", "動態公式", "設備狀態監控"], state="readonly", width=38); self.cmb_type.grid(row=1, column=1, pady=2); self.cmb_type.bind("<<ComboboxSelected>>", self.on_type_change); self.frm_standard = ttk.Frame(master); self.frm_standard.grid(row=2, column=0, columnspan=2, sticky="ew"); self.frm_monitor = ttk.Frame(master); self.lbl_value = ttk.Label(self.frm_standard, text="來源/內容:"); self.lbl_value.grid(row=0, sticky="w", padx=5); self.cmb_url = ttk.Combobox(self.frm_standard, values=self.url_list, state="readonly", width=40); self.ent_value = ttk.Entry(self.frm_standard, width=42)
        ttk.Label(self.frm_monitor, text="狀態URL:").grid(row=0, column=0, sticky="w", padx=5, pady=3); self.cmb_monitor_url = ttk.Combobox(self.frm_monitor, values=self.url_list, state="readonly", width=38); self.cmb_monitor_url.grid(row=0, column=1, pady=3); ttk.Label(self.frm_monitor, text="設備唯一ID:").grid(row=1, column=0, sticky="w", padx=5, pady=3); self.ent_monitor_device_id = ttk.Entry(self.frm_monitor, width=40); self.ent_monitor_device_id.grid(row=1, column=1, pady=3); ttk.Label(self.frm_monitor, text="開機回傳值:").grid(row=2, column=0, sticky="w", padx=5, pady=3); self.ent_monitor_on_val = ttk.Entry(self.frm_monitor, width=40); self.ent_monitor_on_val.grid(row=2, column=1, pady=3); ttk.Label(self.frm_monitor, text="關機回傳值:").grid(row=3, column=0, sticky="w", padx=5, pady=3); self.ent_monitor_off_val = ttk.Entry(self.frm_monitor, width=40); self.ent_monitor_off_val.grid(row=3, column=1, pady=3); ttk.Label(self.frm_monitor, text="提示: 使用此類型，範本需包含\ndevice_id, start_time, end_time,\nduration_seconds等欄位。", foreground="blue").grid(row=4, column=0, columnspan=2, pady=5)
        if self.initial_data:
            self.ent_name.insert(0, self.initial_data.get('name', '')); col_type = self.initial_data.get('type', 'URL'); self.cmb_type.set(col_type); value = self.initial_data.get('value', '')
            if col_type == 'URL': display_text = next((text for text, uid in self.url_display_map.items() if str(uid) == value), ""); self.cmb_url.set(display_text)
            elif col_type == '設備狀態監控' and isinstance(value, dict):
                 url_id = value.get('url_id', ''); display_text = next((text for text, uid in self.url_display_map.items() if str(uid) == str(url_id)), ""); self.cmb_monitor_url.set(display_text); self.ent_monitor_device_id.insert(0, value.get('device_id', '')); self.ent_monitor_on_val.insert(0, value.get('on_val', '255')); self.ent_monitor_off_val.insert(0, value.get('off_val', '0'))
            else: self.ent_value.insert(0, value)
        else: self.cmb_type.current(0); self.ent_monitor_on_val.insert(0, '255'); self.ent_monitor_off_val.insert(0, '0')
        self.on_type_change(); return self.ent_name
    def on_type_change(self, event=None):
        self.frm_standard.grid_forget(); self.frm_monitor.grid_forget(); selected_type = self.cmb_type.get()
        if selected_type == "設備狀態監控":
            self.frm_monitor.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5); self.ent_name.config(state="normal")
            if not self.initial_data: self.ent_name.delete(0, tk.END); self.ent_name.insert(0, "monitor_control")
            self.ent_name.config(state="readonly")
        else:
            self.ent_name.config(state="normal"); self.frm_standard.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5); self.cmb_url.grid_forget(); self.ent_value.grid_forget()
            if selected_type == "URL": self.cmb_url.grid(row=0, column=1, pady=2)
            else:
                self.ent_value.grid(row=0, column=1, pady=2)
                if selected_type == "動態公式" and not self.ent_value.get(): self.ent_value.insert(0, "now | db_eval:get_diff('col', 1)")
    def apply(self):
        name = self.ent_name.get().strip(); col_type = self.cmb_type.get(); value = None
        if not name or (not name.isidentifier() and col_type != '設備狀態監控'): messagebox.showerror("錯誤", "欄位名稱不正確...", parent=self.editor_parent); self.ent_name.focus_set(); return
        if col_type == "URL":
            display_val = self.cmb_url.get();
            if not display_val: messagebox.showerror("錯誤", "請選擇一個URL", parent=self.editor_parent); self.cmb_url.focus_set(); return
            value = str(self.url_display_map.get(display_val, ''))
        elif col_type == "設備狀態監控":
            url_display = self.cmb_monitor_url.get(); device_id = self.ent_monitor_device_id.get().strip(); on_val = self.ent_monitor_on_val.get().strip(); off_val = self.ent_monitor_off_val.get().strip()
            if not all([url_display, device_id, on_val, off_val]): messagebox.showerror("錯誤", "監控設定的所有欄位都不能為空", parent=self.editor_parent); return
            value = {"url_id": str(self.url_display_map.get(url_display)), "device_id": device_id, "on_val": on_val, "off_val": off_val}
        else:
            value = self.ent_value.get().strip()
            if not value: messagebox.showerror("錯誤", "來源內容不能為空", parent=self.editor_parent); self.ent_value.focus_set(); return
        self.result = {"name": name, "type": col_type, "value": value}

# 在 data_collector.py 中，找到 class AnalysisWindow(tk.Toplevel): 並用以下完整內容替換

class AnalysisWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("圖表分析與報告匯出")
        self.geometry("850x750")
        self.transient(parent)

        if not MATPLOTLIB_AVAILABLE or not TKCALENDAR_AVAILABLE:
            messagebox.showerror("缺少函式庫", "請先安裝 pandas, matplotlib, openpyxl 和 tkcalendar 函式庫以使用此功能。\npip install pandas matplotlib openpyxl tkcalendar", parent=self)
            self.destroy()
            return

        self.setup_widgets()
        self.grab_set()
        self.wait_window()

    def setup_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        settings_panel = ttk.Frame(main_frame)
        settings_panel.pack(fill=tk.X)
        source_frame = ttk.LabelFrame(settings_panel, text="1. 選擇資料來源與時間")
        source_frame.pack(fill=tk.X)
        
        ttk.Label(source_frame, text="資料表:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.cmb_tables = ttk.Combobox(source_frame, values=get_table_names(), state="readonly", width=25)
        self.cmb_tables.grid(row=0, column=1, padx=5, pady=5)
        self.cmb_tables.bind("<<ComboboxSelected>>", self.on_table_select)

        ttk.Label(source_frame, text="時間群組:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.cmb_grouping = ttk.Combobox(source_frame, values=['每日統計 (每小時)', '月度統計 (每日)', '年度統計 (每月)'], state="readonly", width=15)
        self.cmb_grouping.grid(row=0, column=3, padx=5, pady=5)
        self.cmb_grouping.set('月度統計 (每日)')
        self.cmb_grouping.bind("<<ComboboxSelected>>", self._on_grouping_change)

        self.time_range_frame = ttk.Frame(source_frame)
        self.time_range_frame.grid(row=1, column=0, columnspan=5, pady=5)
        self._setup_time_range()

        ttk.Label(source_frame, text="時間欄位 (X軸):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        self.cmb_date_col = ttk.Combobox(source_frame, state="readonly", width=25)
        self.cmb_date_col.grid(row=2, column=1, padx=5, pady=5)
        
        analysis_frame = ttk.LabelFrame(settings_panel, text="2. 設定分析欄位 (Y軸)")
        analysis_frame.pack(fill=tk.X)
        self.fields = [self._create_analysis_field(analysis_frame, "欄位 1"), self._create_analysis_field(analysis_frame, "欄位 2")]
        self.fields[0]['frame'].pack(fill=tk.X, padx=5, pady=2)
        self.fields[1]['frame'].pack(fill=tk.X, padx=5, pady=2)

        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(action_frame, text="產生預覽圖表", command=self.on_preview_chart).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="匯出分析報告 (Excel)", command=self.on_export_excel).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="關閉", command=self.destroy).pack(side=tk.RIGHT, padx=5)

        chart_frame = ttk.LabelFrame(main_frame, text="3. 圖表預覽")
        chart_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.ax1 = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)


    def _setup_time_range(self):
        current_year = datetime.datetime.now().year
        years = list(range(current_year - 10, current_year + 2))
        months = list(range(1, 13))

        self.frame_daily = ttk.Frame(self.time_range_frame)
        ttk.Label(self.frame_daily, text="選擇日期:").pack(side=tk.LEFT, padx=5)
        self.cal_daily = DateEntry(self.frame_daily, width=12, date_pattern='y-mm-dd')
        self.cal_daily.pack(side=tk.LEFT)

        self.frame_monthly = ttk.Frame(self.time_range_frame)
        ttk.Label(self.frame_monthly, text="選擇年月:").pack(side=tk.LEFT, padx=5)
        self.spin_month_y = ttk.Spinbox(self.frame_monthly, values=years, width=6)
        self.spin_month_y.pack(side=tk.LEFT)
        ttk.Label(self.frame_monthly, text="年").pack(side=tk.LEFT, padx=(0, 2))
        self.spin_month_m = ttk.Spinbox(self.frame_monthly, values=months, width=4)
        self.spin_month_m.pack(side=tk.LEFT)
        ttk.Label(self.frame_monthly, text="月").pack(side=tk.LEFT)
        self.spin_month_y.set(current_year)
        self.spin_month_m.set(datetime.datetime.now().month)

        self.frame_yearly = ttk.Frame(self.time_range_frame)
        ttk.Label(self.frame_yearly, text="選擇年份:").pack(side=tk.LEFT, padx=5)
        self.spin_year = ttk.Spinbox(self.frame_yearly, values=years, width=8)
        self.spin_year.pack(side=tk.LEFT)
        self.spin_year.set(current_year)
    
    def _on_grouping_change(self, event=None):
        self.frame_daily.pack_forget()
        self.frame_monthly.pack_forget()
        self.frame_yearly.pack_forget()
        grouping = self.cmb_grouping.get()
        if grouping.startswith('每日'):
            self.frame_daily.pack()
        elif grouping.startswith('月度'):
            self.frame_monthly.pack()
        elif grouping.startswith('年度'):
            self.frame_yearly.pack()

    def _create_analysis_field(self, parent, title):
        frame = ttk.Frame(parent)
        chk_var = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(frame, text=title, variable=chk_var)
        chk.grid(row=0, column=0, padx=5)
        ttk.Label(frame, text="分析欄位:").grid(row=0, column=1)
        cmb_col = ttk.Combobox(frame, state="readonly", width=15)
        cmb_col.grid(row=0, column=2, padx=5)
        ttk.Label(frame, text="統計方式:").grid(row=0, column=3)
        cmb_agg = ttk.Combobox(frame, values=['累加 (Sum)', '平均 (Avg)'], state="readonly", width=12)
        cmb_agg.grid(row=0, column=4, padx=5)
        cmb_agg.set('累加 (Sum)')
        ttk.Label(frame, text="圖表類型:").grid(row=0, column=5)
        cmb_chart = ttk.Combobox(frame, values=['直條圖', '折線圖'], state="readonly", width=10)
        cmb_chart.grid(row=0, column=6, padx=5)
        cmb_chart.set('直條圖')
        return {'frame': frame, 'chk_var': chk_var, 'cmb_col': cmb_col, 'cmb_agg': cmb_agg, 'cmb_chart': cmb_chart}

    def on_table_select(self, event=None):
        table_name = self.cmb_tables.get()
        if not table_name: return
        try:
            columns, _ = get_table_data(table_name)
            self.cmb_date_col['values'] = columns
            likely_date_cols = [c for c in columns if any(keyword in c.lower() for keyword in ['time', 'date'])]
            if likely_date_cols:
                self.cmb_date_col.set(likely_date_cols[0])
            elif columns:
                self.cmb_date_col.set(columns[0])
            
            num_cols = sorted([c for c in columns if 'id' not in c.lower() and 'device' not in c.lower()])
            for field in self.fields:
                field['cmb_col']['values'] = num_cols
            if num_cols:
                self.fields[0]['cmb_col'].set(num_cols[0])
                if len(num_cols) > 1:
                    self.fields[1]['cmb_col'].set(num_cols[1])
        except Exception as e:
            messagebox.showerror("錯誤", f"讀取資料表欄位失敗: {e}", parent=self)

    def _get_analysis_params(self):
        table = self.cmb_tables.get()
        date_col = self.cmb_date_col.get()
        grouping = self.cmb_grouping.get()
        
        if not all([table, date_col, grouping]):
            messagebox.showwarning("參數不完整", "請選擇資料表、時間欄位和時間群組。", parent=self)
            return None
        
        try:
            if grouping.startswith('每日'):
                sel_date = self.cal_daily.get_date()
                start_dt = datetime.datetime.combine(sel_date, datetime.time.min)
                end_dt = datetime.datetime.combine(sel_date, datetime.time.max)
                group_by_logic = lambda ts: ts.hour
                index_name = '小時'
            elif grouping.startswith('月度'):
                year, month = int(self.spin_month_y.get()), int(self.spin_month_m.get())
                start_dt = datetime.datetime(year, month, 1)
                _, last_day = calendar.monthrange(year, month)
                end_dt = datetime.datetime(year, month, last_day, 23, 59, 59)
                group_by_logic = lambda ts: ts.day
                index_name = '日期 (日)'
            elif grouping.startswith('年度'):
                year = int(self.spin_year.get())
                start_dt = datetime.datetime(year, 1, 1)
                end_dt = datetime.datetime(year, 12, 31, 23, 59, 59)
                group_by_logic = lambda ts: ts.month
                index_name = '月份'
        except (ValueError, TypeError) as e:
            messagebox.showerror("錯誤", f"時間選擇無效，請檢查輸入: {e}", parent=self)
            return None
        
        conn = sqlite3.connect(DB_NAME)
        try:
            query = f'SELECT * FROM "{table}" WHERE "{date_col}" BETWEEN ? AND ?'
            df = pd.read_sql_query(query, conn, params=(start_dt, end_dt))
        except Exception as e:
            messagebox.showerror("資料庫錯誤", f"從資料庫讀取資料失敗: {e}", parent=self)
            conn.close()
            return None
        finally:
            conn.close()

        if df.empty:
            messagebox.showinfo("提示", f"在指定的時間範圍 ({start_dt.date()} 至 {end_dt.date()}) 內找不到資料。", parent=self)
            return None

        try:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            invalid_dates = df[date_col].isnull().sum()
            if invalid_dates > 0 and invalid_dates < len(df):
                messagebox.showwarning("資料警告", f"欄位 '{date_col}' 中有 {invalid_dates} 筆資料無法解析為有效日期，已被忽略。", parent=self)
            if df[date_col].isnull().all():
                messagebox.showerror("資料格式錯誤", f"您選擇的時間欄位 '{date_col}' 無法被解析為有效的日期時間格式。\n請選擇其他欄位。", parent=self)
                return None
            df.dropna(subset=[date_col], inplace=True)
        except Exception as e:
            messagebox.showerror("資料處理錯誤", f"無法解析時間欄位 '{date_col}': {e}", parent=self)
            return None

        agg_dict = {}
        plot_info = []
        for field in self.fields:
            if field['chk_var'].get():
                col = field['cmb_col'].get()
                agg_method = 'sum' if 'Sum' in field['cmb_agg'].get() else 'mean'
                if col and agg_method:
                    try:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                        invalid_nums = df[col].isnull().sum()
                        if invalid_nums > 0 and invalid_nums < len(df):
                            messagebox.showwarning("資料警告", f"欄位 '{col}' 中有 {invalid_nums} 筆資料無法轉換為數值，已設為 0。", parent=self)
                        df[col].fillna(0, inplace=True)
                        agg_dict[col] = agg_method
                        plot_info.append({'col': col, 'chart_type': field['cmb_chart'].get()})
                    except Exception as e:
                        messagebox.showerror("資料處理錯誤", f"無法處理欄位 '{col}': {e}", parent=self)
                        return None
        if not agg_dict:
            messagebox.showwarning("未選分析欄位", "請至少勾選並設定一個分析欄位。", parent=self)
            return None

        try:
            df_grouped = df.groupby(df[date_col].dt.floor('S').apply(group_by_logic)).agg(agg_dict)
            df_grouped = df_grouped.loc[df_grouped.any(axis=1)]
            
            if df_grouped.empty:
                messagebox.showinfo("提示", "在指定時間範圍內，選取的欄位無有效數據可顯示。", parent=self)
                return None
            
            df_grouped.index.name = index_name
            return df_grouped, plot_info
        except Exception as e:
            messagebox.showerror("資料處理錯誤", f"分組與聚合資料時發生錯誤: {e}", parent=self)
            return None

    def on_preview_chart(self):
        result = self._get_analysis_params()
        if not result:
            return
        
        aggregated_df, plot_info = result
        self.figure.clear()
        self.ax1 = self.figure.add_subplot(111)
        self.ax2 = None
        
        active_plots_info = [info for info in plot_info if info['col'] in aggregated_df.columns]
        if len(active_plots_info) > 1:
            self.ax2 = self.ax1.twinx()

        colors = ['#1f77b4', '#ff7f0e']
        lines, labels = [], []
        
        x_ticks = range(len(aggregated_df.index))
        x_labels = aggregated_df.index.astype(str)

        for i, info in enumerate(active_plots_info):
            ax = self.ax1 if i == 0 else self.ax2
            col_name = info['col']
            chart_type = info['chart_type']
            
            field_widget = next((f for f in self.fields if f['cmb_col'].get() == col_name), self.fields[i])
            agg_method_text = field_widget['cmb_agg'].get().split(' ')[0]
            label = f"{col_name} ({agg_method_text})"

            if chart_type == '直條圖':
                bar_width = 0.4
                offset = -bar_width/2 if len(active_plots_info) > 1 and i == 0 else bar_width/2 if len(active_plots_info) > 1 else 0
                bar_container = ax.bar([x + offset for x in x_ticks], aggregated_df[col_name], color=colors[i], alpha=0.7, label=label, width=bar_width)
                lines.append(bar_container[0])
            else:
                line_plot = ax.plot(x_ticks, aggregated_df[col_name], color=colors[i], marker='o', label=label)
                lines.append(line_plot[0])
            
            labels.append(label)
            ax.set_ylabel(col_name, color=colors[i])
            ax.tick_params(axis='y', labelcolor=colors[i])

        self.ax1.set_xticks(x_ticks)
        self.ax1.set_xticklabels(x_labels, rotation=45, ha='right')
        self.ax1.set_xlabel(aggregated_df.index.name or '時間')
        
        self.figure.tight_layout(rect=[0, 0, 1, 0.95])
        self.figure.legend(lines, labels, title="圖例", loc='upper right')
        self.figure.suptitle("資料分析圖表")
        self.canvas.draw()

    def on_export_excel(self):
        result = self._get_analysis_params()
        if not result:
            return
        aggregated_df, _ = result
        save_path = filedialog.asksaveasfilename(defaultextension=".xlsx", 
                                                filetypes=[("Excel 活頁簿", "*.xlsx"), ("所有檔案", "*.*")], 
                                                title="請選擇儲存位置與檔名")
        if not save_path:
            return
        try:
            self.on_preview_chart()
            img_data = io.BytesIO()
            self.figure.savefig(img_data, format='png', dpi=300, bbox_inches='tight')
            img_data.seek(0)
            with pd.ExcelWriter(save_path, engine='openpyxl') as writer:
                aggregated_df.to_excel(writer, sheet_name='分析數據')
                ws = writer.sheets['分析數據']
                img = OpenpyxlImage(img_data)
                img.anchor = f'A{len(aggregated_df) + 5}'
                ws.add_image(img)
            messagebox.showinfo("成功", f"報告已成功匯出至:\n{save_path}", parent=self)
        except Exception as e:
            messagebox.showerror("匯出失敗", f"匯出 Excel 報告時發生錯誤:\n{e}", parent=self)
class App:
    def __init__(self, root):
        self.root = root; self.root.title("URL 管理與自動抓取工具 v3.9"); self.root.geometry("800x650"); self.auto_run_thread = None; self.stop_auto_run = threading.Event(); self.is_auto_running = False; self.setup_ui(); self.refresh_all(); self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    def setup_ui(self):
        main_frame = ttk.Frame(self.root); main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        paned_window = ttk.PanedWindow(main_frame, orient="vertical"); paned_window.pack(fill="both", expand=True)
        frm_templates = ttk.LabelFrame(paned_window, text="1. 資料抓取範本列表與控制")
        paned_window.add(frm_templates, weight=2)
        frm_templates.grid_rowconfigure(0, weight=1)
        frm_templates.grid_columnconfigure(0, weight=1)
        self.tree_templates = ttk.Treeview(frm_templates, show="headings", selectmode="extended"); self.tree_templates["columns"] = ("ID", "範本名稱", "說明", "唯一鍵", "上次執行")
        for col in self.tree_templates["columns"]: self.tree_templates.heading(col, text=col); self.tree_templates.column(col, anchor="w")
        self.tree_templates.column("ID", width=40, anchor="center"); self.tree_templates.column("範本名稱", width=150); self.tree_templates.column("說明", width=200); self.tree_templates.column("唯一鍵", width=100);         self.tree_templates.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        frm_template_btns = ttk.Frame(frm_templates); frm_template_btns.grid(row=1, column=0, sticky="ew", padx=5, pady=5); ttk.Button(frm_template_btns, text="新增範本", command=self.open_template_editor).pack(side="left"); ttk.Button(frm_template_btns, text="編輯選取", command=self.edit_selected_template).pack(side="left", padx=5); ttk.Button(frm_template_btns, text="執行選取", command=self.run_selected_templates).pack(side="left", padx=5); ttk.Button(frm_template_btns, text="管理 URL", command=self.open_url_manager).pack(side="left", padx=5); ttk.Button(frm_template_btns, text="圖表分析", command=self.open_analysis_window).pack(side="left", padx=5); ttk.Button(frm_template_btns, text="刪除選取", command=self.delete_selected_templates).pack(side="right")
        frm_auto_run = ttk.LabelFrame(frm_templates, text="自動執行設定"); frm_auto_run.grid(row=2, column=0, sticky="ew", padx=5, pady=5); ttk.Label(frm_auto_run, text="間隔(秒):").pack(side="left", padx=(5,0)); self.ent_interval = ttk.Entry(frm_auto_run, width=5); self.ent_interval.insert(0, "60"); self.ent_interval.pack(side="left", padx=(0,10)); self.btn_auto_run = ttk.Button(frm_auto_run, text="開始自動執行", command=self.toggle_auto_run); self.btn_auto_run.pack(side="left"); self.status_label = ttk.Label(frm_auto_run, text="狀態：已停止", anchor="w"); self.status_label.pack(side="left", padx=10, fill="x", expand=True)
        frm_data_view = ttk.LabelFrame(paned_window, text="2. 資料表檢視"); paned_window.add(frm_data_view, weight=3); frm_table_select = ttk.Frame(frm_data_view); frm_table_select.pack(fill="x", padx=5, pady=5); ttk.Label(frm_table_select, text="選擇資料表:").pack(side="left"); self.cmb_tables = ttk.Combobox(frm_table_select, state="readonly", width=30); self.cmb_tables.pack(side="left", padx=5); self.cmb_tables.bind("<<ComboboxSelected>>", lambda e: self.on_load_table()); ttk.Button(frm_table_select, text="刷新列表", command=self.refresh_table_list).pack(side="left"); ttk.Button(frm_table_select, text="刷新內容", command=lambda: self.on_load_table(True)).pack(side="left", padx=5); ttk.Button(frm_table_select, text="清空此表內容", command=self.on_clear_table, style="Danger.TButton").pack(side="right"); style = ttk.Style(); style.configure("Danger.TButton", foreground="red")
        self.tree_data = ttk.Treeview(frm_data_view, show="headings"); self.tree_data.pack(fill="both", expand=True, padx=5, pady=5)
    def refresh_all(self): self.refresh_template_list(); self.refresh_table_list()
    def refresh_template_list(self): self.tree_templates.delete(*self.tree_templates.get_children()); [self.tree_templates.insert("", "end", iid=r['id'], values=(r['id'], r['template_name'], r['description'] or "", r['unique_key_column'] or "無", r['last_run_time'] or "從未")) for r in get_templates()]
    def refresh_table_list(self):
        current_table = self.cmb_tables.get(); tables = get_table_names(); self.cmb_tables['values'] = tables
        if current_table in tables: self.cmb_tables.set(current_table)
        elif tables: self.cmb_tables.current(0)
        else: self.cmb_tables.set('')
        self.on_load_table()
    def open_analysis_window(self): AnalysisWindow(self.root)
    def open_template_editor(self): TemplateEditor(self.root, self)
    def open_url_manager(self): UrlManagerWindow(self.root)
    def edit_selected_template(self):
        selected = self.tree_templates.selection()
        if not selected: messagebox.showwarning("警告", "請選擇一個要編輯的範本"); return
        if len(selected) > 1: messagebox.showwarning("警告", "一次只能編輯一個範本"); return
        TemplateEditor(self.root, self, selected[0])
    def run_selected_templates(self):
        selected = self.tree_templates.selection();
        if not selected: messagebox.showwarning("警告", "請選擇要執行的範本"); return
        if not messagebox.askyesno("確認執行", f"確定要執行選取的 {len(selected)} 個範本嗎？"): return
        url_map = {r['id']: (r['url'], r['description']) for r in get_urls()}; total = len(selected); success_count, failed_list = 0, []
        for template_id in selected:
            template_name = self.tree_templates.item(template_id, 'values')[1]; self.update_status(f"正在執行: {template_name}..."); self.root.update_idletasks()
            ok, msg = run_template(template_id, url_map)
            if not ok: failed_list.append(f"{template_name}: {msg}")
            else: success_count += 1
        self.update_status("手動執行完畢。"); self.refresh_all(); self.on_load_table(True)
        summary = f"執行完畢。\n\n成功: {success_count}/{total} 個範本。"
        if failed_list: summary += "\n\n失敗詳情:\n" + "\n".join(failed_list)
        messagebox.showinfo("執行結果", summary)
    def delete_selected_templates(self):
        selected = self.tree_templates.selection()
        if not selected: messagebox.showwarning("警告", "請選擇要刪除的範本"); return
        msg = f"確定要刪除選取的 {len(selected)} 個範本嗎？\n\n這將會一併刪除對應的資料表及其所有資料！\n\n此操作無法復原。"
        if messagebox.askyesno("極度危險！確認刪除", msg, icon='warning'):
            for template_id in selected: delete_template(template_id)
            messagebox.showinfo("成功", "選取的範本與資料表已刪除"); self.refresh_all()
    def on_load_table(self, force_refresh=False):
        table = self.cmb_tables.get()
        if not table: self.tree_data.delete(*self.tree_data.get_children()); self.tree_data["columns"] = (); return
        needs_refresh = force_refresh
        if not needs_refresh:
            try:
                columns, _ = get_table_data(table)
                if tuple(columns) != self.tree_data['columns']: needs_refresh = True
            except Exception: needs_refresh = True
        if needs_refresh:
            self.tree_data.delete(*self.tree_data.get_children()); columns, rows = get_table_data(table); self.tree_data["columns"] = columns
            for col in columns: self.tree_data.heading(col, text=col); self.tree_data.column(col, width=120, anchor="w")
            for row in rows: self.tree_data.insert("", "end", values=tuple(row))
    def on_clear_table(self):
        table_to_clear = self.cmb_tables.get()
        if not table_to_clear: messagebox.showwarning("警告", "請先選擇一個要清空的資料表。"); return
        msg = f"您確定要刪除資料表 '{table_to_clear}' 中的【所有資料】嗎？\n\n資料表的結構會被保留，但所有紀錄都將被永久刪除。\n\n此操作無法復原！"
        if messagebox.askyesno("危險操作確認", msg, icon='warning'):
            ok, result_msg = clear_table_data(table_to_clear)
            if ok: messagebox.showinfo("成功", result_msg); self.on_load_table(True)
            else: messagebox.showerror("失敗", result_msg)
    def update_status(self, message): self.status_label.config(text=f"狀態：{message}")
    def _auto_run_loop(self, selected_ids, interval_seconds, id_to_name_map):
        url_map = {r['id']: (r['url'], r['description']) for r in get_urls()}
        while not self.stop_auto_run.is_set():
            total, success_count = len(selected_ids), 0
            for template_id in selected_ids:
                if self.stop_auto_run.is_set(): break
                template_name = id_to_name_map.get(template_id, f"ID {template_id}"); self.root.after(0, self.update_status, f"自動執行中: {template_name}...")
                ok, _ = run_template(template_id, url_map); 
                if ok: success_count += 1
                time.sleep(0.1)
            if self.stop_auto_run.is_set(): break
            next_run_time = datetime.datetime.now() + datetime.timedelta(seconds=interval_seconds); status_msg = f"執行完畢 ({success_count}/{total})。下次執行: {next_run_time.strftime('%H:%M:%S')}"
            self.root.after(0, self.update_status, status_msg); self.root.after(0, self.refresh_all); self.root.after(0, self.on_load_table, True)
            if self.stop_auto_run.wait(timeout=interval_seconds): break
    def toggle_auto_run(self):
        if self.is_auto_running:
            self.stop_auto_run.set(); self.btn_auto_run.config(state="disabled"); self.update_status("正在停止..."); self.root.after(100, self.check_thread_stopped)
        else:
            try: interval_seconds = float(self.ent_interval.get())
            except ValueError: messagebox.showerror("錯誤", "請輸入有效的數字作為間隔秒數"); return
            if interval_seconds < 1: messagebox.showerror("錯誤", "間隔秒數必須大於等於1"); return
            selected_ids = self.tree_templates.selection()
            if not selected_ids: messagebox.showwarning("警告", "請先在列表中選取至少一個要自動執行的範本"); return
            id_to_name_map = {tid: self.tree_templates.item(tid, 'values')[1] for tid in selected_ids}
            self.is_auto_running = True; self.stop_auto_run.clear(); self.btn_auto_run.config(text="停止自動執行"); self.update_status("已啟動...")
            self.auto_run_thread = threading.Thread(target=self._auto_run_loop, args=(selected_ids, interval_seconds, id_to_name_map), daemon=True); self.auto_run_thread.start()
    def check_thread_stopped(self):
        if self.auto_run_thread and self.auto_run_thread.is_alive(): self.root.after(100, self.check_thread_stopped)
        else:
            self.is_auto_running = False; self.auto_run_thread = None; self.btn_auto_run.config(text="開始自動執行", state="normal"); self.update_status("已停止"); messagebox.showinfo("提示", "自動執行已停止。")
    def on_closing(self):
        if self.is_auto_running:
            if messagebox.askokcancel("關閉", "自動執行正在運行中。確定要停止並關閉程式嗎？"):
                self.stop_auto_run.set()
                if self.auto_run_thread: self.auto_run_thread.join(timeout=2)
                self.root.destroy()
        else:
            self.root.destroy()

if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    if not MATPLOTLIB_AVAILABLE or not TKCALENDAR_AVAILABLE or 'pd' not in globals():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("缺少必要函式庫", "此應用程式需要 pandas, matplotlib, openpyxl 和 tkcalendar 函式庫。\n請透過 pip 安裝它們:\n\npip install pandas matplotlib openpyxl tkcalendar")
    else:
        init_db()
        root = tk.Tk()
        app = App(root)
        root.mainloop()