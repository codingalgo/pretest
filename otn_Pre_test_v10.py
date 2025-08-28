#!/usr/bin/env python3
# serial_test_tool_pro.py
"""
Serial Test Tool — Modern UI version
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import serial, serial.tools.list_ports
import threading, time, json, os, re, webbrowser, csv
from datetime import datetime
from html import escape as html_escape
import textwrap

APP_TITLE = "Serial Test Tool — Modern UI"
SESSION_LOG = "session.log"

# JSON schema fields
JSON_FIELDS = ["command_name","command","expected","expected_regex","negative",
    "wait_till","print_after","print_ahead_chars","message","retries"]
DEFAULT_ROW = {
    "command_name":"", "command":"", "expected":"", "expected_regex":"",
    "negative":False, "wait_till":1.0, "print_after":"", "print_ahead_chars":40,
    "message":"", "retries":0
}

def now(fmt="%Y-%m-%d %H:%M:%S.%f"):
    return datetime.now().strftime(fmt)[:-3]

def safe_int(v, default=0):
    try: return int(v)
    except: return default

def safe_float(v, default=1.0):
    try: return float(v)
    except: return default

def normalize_row(row):
    out = DEFAULT_ROW.copy()
    if not isinstance(row, dict): return out
    for k in JSON_FIELDS:
        if k in row: out[k] = row[k]
    out["negative"] = bool(out.get("negative", False))
    out["wait_till"] = safe_float(out.get("wait_till", 1.0))
    out["print_ahead_chars"] = safe_int(out.get("print_ahead_chars", 40))
    out["retries"] = safe_int(out.get("retries", 0))
    return out

def wrap_text(text, width=50):
    """Wrap text for multi-line Treeview cells."""
    return "\n".join(textwrap.wrap(text, width=width))

# ---------------------- Main Class ----------------------
class SerialTestTool:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1400x900")
        self.root.minsize(1100, 700)
        self.ser = None
        self.reader_running = False
        self.tests = []
        self.results = []
        self.json_path = None
        self.buf_lock = threading.Lock()
        self.shared_lines = []
        self.stop_flag = False
        self.export_enabled = False
        self._drag_iid = None

        self._init_styles()
        self._build_ui()

        try:
            with open(SESSION_LOG,"w",encoding="utf-8") as f:
                f.write(f"[{now()}] {APP_TITLE} started\n")
        except:
            pass

    def _init_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except:
            pass

        BIG_FONT = ("Segoe UI", 12)
        BIG_FONT_BOLD = ("Segoe UI", 12, "bold")
        TREE_FONT = ("Segoe UI", 12)

        self.root.option_add("*Font", BIG_FONT)
        self.root.option_add("*TButton.padding", 10)
        self.root.option_add("*Label.padding", 6)
        self.root.option_add("*Entry.padding", 6)

        # Treeview
        style.configure("Treeview", rowheight=34, font=TREE_FONT,
                        borderwidth=1, relief="solid",
                        background="#FFFFFF", fieldbackground="#FFFFFF")
        style.configure("Treeview.Heading", font=BIG_FONT_BOLD, padding=10,
                        relief="solid", background="#E5E7EB", foreground="#111")
        style.layout("Treeview", [("Treeview.treearea", {"sticky":"nswe"})])

        # Buttons
        style.configure("TButton", padding=12, relief="flat", font=BIG_FONT)

        # Progress bar
        style.configure("Horizontal.TProgressbar", thickness=18)

        # LabelFrame
        style.configure("TLabelframe", padding=14, font=BIG_FONT_BOLD)
        style.configure("TLabelframe.Label", font=BIG_FONT_BOLD)
    # ---------- Build UI ----------
    def _build_ui(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)
        self._build_connection_tab()
        self._build_editor_tab()
        self._build_run_tab()

    # ---------- Connection Tab ----------
    def _build_connection_tab(self):
        f = ttk.Frame(self.nb, padding=20)
        self.nb.add(f, text="Connection")

        card = ttk.LabelFrame(f, text=" Serial Port Setup ", padding=20)
        card.pack(fill="x", pady=10)

        # Row 1: Serial Port
        row1 = ttk.Frame(card)
        row1.pack(fill="x", pady=8)
        ttk.Label(row1, text="Serial Port:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=6)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(row1, textvariable=self.port_var, width=40,
                                       values=self._list_ports(), state="readonly")
        self.port_combo.pack(side="left", padx=6)
        ttk.Button(row1, text="🔄 Refresh", command=lambda: self.port_combo.config(values=self._list_ports())).pack(side="left", padx=6)

        # Row 2: Baud Rate
        row2 = ttk.Frame(card)
        row2.pack(fill="x", pady=8)
        ttk.Label(row2, text="Baud Rate:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=6)
        self.baud_var = tk.StringVar(value="115200")
        ttk.Combobox(row2, textvariable=self.baud_var, width=20,
                     values=["9600","19200","38400","57600","115200","230400"],
                     state="readonly").pack(side="left", padx=6)

        # Row 3: Buttons
        btns = ttk.Frame(card)
        btns.pack(fill="x", pady=10)
        self.btn_connect = ttk.Button(btns, text="✅ Connect", command=self.connect, width=16)
        self.btn_connect.pack(side="left", padx=10)
        self.btn_disconnect = ttk.Button(btns, text="❌ Disconnect", command=self.disconnect, state="disabled", width=16)
        self.btn_disconnect.pack(side="left", padx=10)

        # Row 4: Status
        self.conn_status = ttk.Label(card, text="🔴 Disconnected", foreground="red", font=("Segoe UI", 11, "bold"))
        self.conn_status.pack(pady=10)

        ttk.Label(f, text="💡 Tip: Connect first, then use Run Tests tab.", font=("Segoe UI", 10), foreground="#555").pack(anchor="w", pady=4)

    def _list_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self):
        port = self.port_var.get()
        baud = safe_int(self.baud_var.get(),115200)
        if not port:
            messagebox.showwarning("Port missing","Select a port.")
            return
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.conn_status.config(text=f"🟢 Connected to {port}", foreground="green")
            self.btn_connect.config(state="disabled")
            self.btn_disconnect.config(state="normal")
            self.reader_running = True
            threading.Thread(target=self._serial_reader,daemon=True).start()
        except Exception as e:
            messagebox.showerror("Error",str(e))

    def disconnect(self):
        self.reader_running = False
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass
        self.conn_status.config(text="🔴 Disconnected", foreground="red")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")

    def _serial_reader(self):
        while self.reader_running:
            try:
                if self.ser and self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting).decode(errors="ignore")
                    if data:
                        with self.buf_lock:
                            self.shared_lines.append(data)
                time.sleep(0.05)
            except:
                time.sleep(0.1)
    # ---------- Test Editor Tab ----------
    def _build_editor_tab(self):
        f = ttk.Frame(self.nb, padding=20)
        self.nb.add(f, text="Test Editor")

        # Toolbar
        toolbar = ttk.Frame(f)
        toolbar.pack(fill="x", pady=5)
        ttk.Button(toolbar, text="📂 Load JSON", command=self.load_json).pack(side="left", padx=5)
        ttk.Button(toolbar, text="💾 Save JSON", command=self.save_json).pack(side="left", padx=5)
        self.editor_search = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.editor_search, width=30).pack(side="right", padx=5)
        ttk.Label(toolbar, text="🔍 Search:").pack(side="right")

        # Treeview
        cols = ("Name","Command","Expected","Regex","Neg","Wait","After","Chars","Msg","Retries")
        self.editor_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.editor_tree.pack(fill="both", expand=True)

        for c in cols:
            self.editor_tree.heading(c, text=c)
            self.editor_tree.column(c, anchor="center", width=100)

        # Row colors
        self.editor_tree.tag_configure("oddrow", background="#F9FAFB")
        self.editor_tree.tag_configure("evenrow", background="#FFFFFF")

        # Refresh button
        ttk.Button(f, text="🔄 Refresh Table", command=self._refresh_editor_tree).pack(pady=10)

    def load_json(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files","*.json")])
        if not path: return
        try:
            with open(path,"r",encoding="utf-8") as f:
                data = json.load(f)
            self.tests = [normalize_row(x) for x in data]
            self.json_path = path
            self._refresh_editor_tree()
            messagebox.showinfo("Loaded",f"Loaded {len(self.tests)} tests.")
        except Exception as e:
            messagebox.showerror("Error",str(e))

    def save_json(self):
        if not self.tests:
            messagebox.showwarning("No data","Nothing to save.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON files","*.json")])
        if not path: return
        try:
            with open(path,"w",encoding="utf-8") as f:
                json.dump(self.tests,f,indent=2)
            messagebox.showinfo("Saved",f"Saved to {path}")
        except Exception as e:
            messagebox.showerror("Error",str(e))

    def _refresh_editor_tree(self):
        self.editor_tree.delete(*self.editor_tree.get_children())
        q = (self.editor_search.get() or "").strip().lower()
        for idx, t in enumerate(self.tests):
            if q:
                hay = " ".join([str(t.get(k,"")).lower() for k in ("command_name","command","expected","message")])
                if q not in hay:
                    continue
            vals = (
                t.get("command_name",""),
                wrap_text(t.get("command","")),
                t.get("expected",""),
                t.get("expected_regex",""),
                "Yes" if t.get("negative",False) else "No",
                t.get("wait_till",1.0),
                t.get("print_after",""),
                t.get("print_ahead_chars",40),
                t.get("message",""),
                t.get("retries",0)
            )
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.editor_tree.insert("", "end", values=vals, tags=(tag,))
                # ---------- Run Tests Tab ----------
    def _build_run_tab(self):
        f = ttk.Frame(self.nb, padding=20)
        self.nb.add(f, text="Run Tests")

        # Controls
        top = ttk.Frame(f)
        top.pack(fill="x", pady=5)
        ttk.Label(top, text="Iterations:").pack(side="left")
        self.iter_var = tk.IntVar(value=1)
        ttk.Entry(top, textvariable=self.iter_var, width=5).pack(side="left", padx=5)
        self.btn_run = ttk.Button(top, text="▶ Run All", command=self.run_all)
        self.btn_run.pack(side="left", padx=5)
        self.btn_stop = ttk.Button(top, text="⏹ Stop", command=self._stop_now, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        self.btn_export_html = ttk.Button(top, text="🌐 Export HTML", command=self.export_html, state="disabled")
        self.btn_export_html.pack(side="left", padx=5)
        self.btn_export_csv = ttk.Button(top, text="📄 Export CSV", command=self.export_csv, state="disabled")
        self.btn_export_csv.pack(side="left", padx=5)

        # Table
        cols = ("Iter","Cmd Name","Cmd","Expected","Regex","Found","Result","Duration","Snippet/Msg")
        self.live_tree = ttk.Treeview(f, columns=cols, show="headings")
        self.live_tree.pack(fill="both", expand=True)
        for c in cols:
            self.live_tree.heading(c, text=c)
            self.live_tree.column(c, anchor="center", width=120)

        # Row colors
        self.live_tree.tag_configure("pending", background="#E5E7EB")
        self.live_tree.tag_configure("running", background="#FEF08A")
        self.live_tree.tag_configure("pass", background="#BBF7D0")
        self.live_tree.tag_configure("fail", background="#FCA5A5")
        self.live_tree.tag_configure("error", background="#FDBA74")

        # Bottom
        bottom = ttk.Frame(f)
        bottom.pack(fill="x", pady=10)
        self.prog = tk.DoubleVar(value=0.0)
        ttk.Progressbar(bottom, variable=self.prog, maximum=100, length=400).pack(side="left", padx=5)
        self.summary = tk.StringVar(value="Ready.")
        ttk.Label(bottom, textvariable=self.summary).pack(side="left", padx=5)

    # ---------- Runner + Markers + Export (SAME AS BEFORE) ----------
    # (Paste the entire Part 3 code I gave earlier with run_all, _run_worker, 
    # _mark_running, _mark_pass, _mark_fail, _mark_error, export_html, export_csv)
    # -------------------    # ---------- Run Logic ----------
    def run_all(self):
        if not self.tests:
            messagebox.showwarning("No tests", "Load a JSON first.")
            return
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("No connection", "Connect to a device first.")
            return

        self.stop_flag = False
        self.results.clear()
        self.live_tree.delete(*self.live_tree.get_children())
        iters = max(1, self.iter_var.get())
        total = len(self.tests) * iters
        self.summary.set(f"Running {total} tests...")
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_export_html.config(state="disabled")
        self.btn_export_csv.config(state="disabled")
        self.prog.set(0)

        # Insert all rows as PENDING
        for it in range(1, iters+1):
            for t in self.tests:
                vals = (
                    it,
                    t.get("command_name",""),
                    wrap_text(t.get("command","")),
                    t.get("expected",""),
                    t.get("expected_regex",""),
                    "",
                    "PENDING",
                    "",
                    ""
                )
                self.live_tree.insert("", "end", values=vals, tags=("pending",))

        threading.Thread(target=self._run_worker, daemon=True).start()

    def _stop_now(self):
        self.stop_flag = True
        self.summary.set("Stopping...")

    def _run_worker(self):
        children = self.live_tree.get_children()
        total = len(children)
        start_time = time.time()

        for idx, iid in enumerate(children, start=1):
            if self.stop_flag:
                break
            self._mark_running(iid)
            self.root.update_idletasks()
            vals = self.live_tree.item(iid, "values")
            cmd = vals[2].replace("\n"," ")
            expected = vals[3]
            regex = vals[4]
            negative = False
            msg = ""

            try:
                if self.ser:
                    self.ser.reset_input_buffer()
                    self.ser.write((cmd+"\r\n").encode())
                    time.sleep(0.1)
                timeout = 3.0
                buf = ""
                t0 = time.time()
                found = False
                while time.time()-t0<timeout:
                    time.sleep(0.05)
                    if self.ser and self.ser.in_waiting:
                        buf += self.ser.read(self.ser.in_waiting).decode(errors="ignore")
                    if expected and expected in buf:
                        found = True
                        break
                    if regex and re.search(regex, buf):
                        found = True
                        break

                dur = time.time()-t0
                snippet = buf.strip()[:80]
                if found ^ negative:
                    self._mark_pass(iid, snippet, msg, dur)
                else:
                    self._mark_fail(iid, snippet, msg, dur)
            except Exception as e:
                self._mark_error(iid, str(e))

            self.prog.set(idx/total*100)
            self.root.update_idletasks()

        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_export_html.config(state="normal")
        self.btn_export_csv.config(state="normal")
        elapsed = time.time()-start_time
        self.summary.set(f"Done. Ran {total} tests in {elapsed:.1f}s.")

    # ---------- Status Markers ----------
    def _mark_running(self, iid):
        vals = list(self.live_tree.item(iid, "values"))
        vals[6] = "RUNNING"
        self.live_tree.item(iid, values=vals, tags=("running",))

    def _mark_pass(self, iid, snippet, msg, dur):
        vals = list(self.live_tree.item(iid, "values"))
        vals[5] = "YES"
        vals[6] = "PASS"
        vals[7] = f"{dur:.2f}"
        vals[8] = msg or snippet
        self.live_tree.item(iid, values=vals, tags=("pass",))

    def _mark_fail(self, iid, snippet, msg, dur):
        vals = list(self.live_tree.item(iid, "values"))
        vals[5] = "NO"
        vals[6] = "FAIL"
        vals[7] = f"{dur:.2f}"
        vals[8] = msg or snippet
        self.live_tree.item(iid, values=vals, tags=("fail",))

    def _mark_error(self, iid, msg):
        vals = list(self.live_tree.item(iid, "values"))
        vals[5] = "?"
        vals[6] = "ERROR"
        vals[8] = msg
        self.live_tree.item(iid, values=vals, tags=("error",))

    # ---------- Export Functions ----------
    def export_html(self):
        path = filedialog.asksaveasfilename(defaultextension=".html",filetypes=[("HTML files","*.html")])
        if not path: return
        rows = []
        for iid in self.live_tree.get_children():
            vals = self.live_tree.item(iid,"values")
            rows.append(vals)
        html = self._generate_html(rows)
        with open(path,"w",encoding="utf-8") as f:
            f.write(html)
        webbrowser.open(path)

    def _generate_html(self, rows):
        head = """
        <html><head><meta charset="utf-8">
        <style>
        body{font-family:Segoe UI,Arial,sans-serif;margin:20px;}
        table{border-collapse:collapse;width:100%;}
        th,td{border:1px solid #ccc;padding:8px;text-align:center;}
        th{background:#E5E7EB;}
        tr.pass{background:#BBF7D0;}
        tr.fail{background:#FCA5A5;}
        tr.error{background:#FDBA74;}
        tr.pending{background:#E5E7EB;}
        tr.running{background:#FEF08A;}
        </style></head><body>
        <h1>Test Results</h1>
        <table><tr>
        <th>Iter</th><th>Name</th><th>Cmd</th><th>Expected</th>
        <th>Regex</th><th>Found</th><th>Result</th>
        <th>Duration</th><th>Msg</th></tr>
        """
        rows_html = ""
        for r in rows:
            cls = r[6].lower()
            rows_html += "<tr class='%s'>%s</tr>\n"%(cls,"".join(f"<td>{html_escape(str(x))}</td>" for x in r))
        return head+rows_html+"</table></body></html>"

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV files","*.csv")])
        if not path: return
        with open(path,"w",newline="",encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(("Iter","Name","Cmd","Expected","Regex","Found","Result","Duration","Msg"))
            for iid in self.live_tree.get_children():
                vals = self.live_tree.item(iid,"values")
                writer.writerow(vals)
        messagebox.showinfo("Saved",f"Saved CSV to {path}")


# ---------- Main ----------
def main():
    root = tk.Tk()
    app = SerialTestTool(root)
    root.mainloop()

if __name__ == "__main__":
    main()

