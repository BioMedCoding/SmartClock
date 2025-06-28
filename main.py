#!/usr/bin/env python3
"""
Home-Automation master GUI for a Raspberry Pi 3 (480×320 TFT).
Fully self-contained & ready for virtual-env installation.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import queue
import threading
import time
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import statistics
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates

# ──────────────────────────────────────────────────────────────────────────────
# Constants & helpers
# ──────────────────────────────────────────────────────────────────────────────
DEMO_MODE = True                      # Set False in production
REFRESH_GUI_MS = 1000                 # 1 s sensor-card refresh
REFRESH_GRAPH_MS = 15000              # 15 s history graph refresh
HISTORY_SECONDS = 2 * 60 * 60         # Store 2 h per sensor
UNITS = {"Temperature": "°C", "Humidity": "%", "Pressure": "hPa"}

APP_BG = "#2c3e50"
CARD_BG = "#34495e"
TEMP_CLR, HUM_CLR, PRES_CLR = "#e74c3c", "#3498db", "#9b59b6"

# ──────────────────────────────────────────────────────────────────────────────
# Bluetooth stub fallback (so GUI runs before comm layer is ready)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from bluetooth_comm import BluetoothCommunication          # real module (future)
except ModuleNotFoundError:
    class BluetoothCommunication:                              # ← stub
        def __init__(self, data_queue: queue.Queue):
            self._q = data_queue
            self._running = False

        def start_communication(self):
            import logging
            logging.warning("BluetoothCommunication stub active – no BT data.")
            self._running = True
            while self._running:
                time.sleep(5)                                  # idle loop

        def stop(self):                                        # called on exit
            self._running = False

# ──────────────────────────────────────────────────────────────────────────────
# Sensor-side data container
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class SensorData:
    sensor_id:   str
    sensor_type: str
    location:    str
    data_history: deque[tuple[datetime, float]] = field(
        default_factory=lambda: deque(maxlen=HISTORY_SECONDS)
    )
    current_value: float | None = None
    last_update: datetime = field(default_factory=datetime.now)

    # GUI widgets attached later
    value_label:  tk.Label | None = None
    update_label: tk.Label | None = None

    # API ---------------------------------------------------------------------
    def add_data(self, value: float, timestamp: datetime | None = None) -> None:
        ts = timestamp or datetime.now()
        self.data_history.append((ts, value))
        self.current_value, self.last_update = value, ts

    def recent_samples(self, minutes: int) -> list[tuple[datetime, float]]:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [(ts, val) for ts, val in self.data_history if ts >= cutoff]

    def stats(self, minutes: int) -> dict | None:
        sample = self.recent_samples(minutes)
        if not sample:
            return None
        vals = [v for _, v in sample]
        return {
            "mean": round(statistics.mean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "std": round(statistics.stdev(vals) if len(vals) > 1 else 0, 2),
            "trend": round(self._trend(sample), 4),
            "count": len(vals),
        }

    def _trend(self, sample):
        if len(sample) < 2:
            return 0.0
        x = np.arange(len(sample))
        y = [v for _, v in sample]
        return np.polyfit(x, y, 1)[0]

# ──────────────────────────────────────────────────────────────────────────────
# History popup window
# ──────────────────────────────────────────────────────────────────────────────
class SensorHistoryWindow:
    def __init__(self, parent: tk.Tk, sensor: SensorData):
        self.sensor = sensor

        self.win = tk.Toplevel(parent, bg=APP_BG)
        self.win.title(f"{sensor.location} – {sensor.sensor_type} History")
        self.win.geometry("800x600")

        self._build_ui()
        self._update_ui()
        self._schedule_refresh()

    # UI builders -------------------------------------------------------------
    def _build_ui(self):
        # title bar
        tk.Label(self.win, text=f"{self.sensor.location} – {self.sensor.sensor_type}",
                 font=("Arial", 16, "bold"), bg=APP_BG, fg="white").pack(pady=6)

        # period selector
        period_fr = tk.Frame(self.win, bg=APP_BG); period_fr.pack()
        tk.Label(period_fr, text="Time Period:", bg=APP_BG, fg="white").pack(side="left")
        self.period_var = tk.IntVar(value=60)
        for txt, val in [("15 min", 15), ("30 min", 30), ("60 min", 60), ("120 min", 120)]:
            tk.Radiobutton(period_fr, text=txt, value=val, variable=self.period_var,
                           bg=APP_BG, fg="white", selectcolor=CARD_BG,
                           command=self._update_ui).pack(side="left", padx=4)

        # statistics box
        self.stats_frame = tk.Frame(self.win, bg=CARD_BG, bd=2, relief="raised")
        self.stats_frame.pack(fill="x", padx=10, pady=8)

        # graph area
        self.graph_frame = tk.Frame(self.win, bg=APP_BG)
        self.graph_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # persistent matplotlib figure
        self.fig, self.ax = plt.subplots(figsize=(4, 2), dpi=100, facecolor=APP_BG)
        self.ax.set_facecolor(CARD_BG)
        self.line, = self.ax.plot([], [], color="#3498db", linewidth=2)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        self.ax.tick_params(colors="white")
        for spine in self.ax.spines.values():
            spine.set_color("white")
        self.ax.grid(True, alpha=0.3, color="white")

        self.canvas = FigureCanvasTkAgg(self.fig, self.graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # close button
        tk.Button(self.win, text="Close", bg="#e74c3c", fg="white",
                  command=self.win.destroy).pack(pady=6)

    # Refresh logic -----------------------------------------------------------
    def _update_ui(self):
        mins = self.period_var.get()
        self._update_stats(mins)
        self._update_graph(mins)

    def _update_stats(self, mins):
        for w in self.stats_frame.winfo_children():
            w.destroy()

        stats = self.sensor.stats(mins)
        if not stats:
            tk.Label(self.stats_frame, text="No data", fg="white", bg=CARD_BG).pack()
            return

        unit = UNITS.get(self.sensor.sensor_type, "")
        fields = [
            ("Current", f"{self.sensor.current_value}{unit}"),
            ("Mean",    f"{stats['mean']}{unit}"),
            ("Median",  f"{stats['median']}{unit}"),
            ("Min",     f"{stats['min']}{unit}"),
            ("Max",     f"{stats['max']}{unit}"),
            ("Std",     f"{stats['std']}{unit}"),
            ("Trend",   f"{stats['trend']}{unit}/sample"),
            ("Samples", str(stats['count'])),
        ]
        for row, (lbl, val) in enumerate(fields):
            tk.Label(self.stats_frame, text=f"{lbl}:", bg=CARD_BG, fg="#ecf0f1",
                     font=("Arial", 9, "bold")).grid(row=row, column=0, sticky="w", padx=4, pady=1)
            tk.Label(self.stats_frame, text=val, bg=CARD_BG, fg="white",
                     font=("Arial", 9)).grid(row=row, column=1, sticky="w", padx=4, pady=1)

    def _update_graph(self, mins):
        data = self.sensor.recent_samples(mins)
        if data:
            ts, vals = zip(*data)
            self.line.set_data(ts, vals)
            self.ax.relim(); self.ax.autoscale_view()
        else:
            self.line.set_data([], [])
        self.canvas.draw_idle()

    def _schedule_refresh(self):
        self._update_ui()
        self.win.after(REFRESH_GRAPH_MS, self._schedule_refresh)

# ──────────────────────────────────────────────────────────────────────────────
# Main application
# ──────────────────────────────────────────────────────────────────────────────
class HomeAutomationGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Home Automation Control")
        self.root.geometry("480x320")
        self.root.configure(bg=APP_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.running = True

        self.data_q: queue.Queue[dict] = queue.Queue()
        self._bluetooth = BluetoothCommunication(self.data_q)
        self._threads: list[threading.Thread] = []

        self._build_sensors()
        self._build_ui()
        self._start_threads()
        if DEMO_MODE:
            self._start_demo_data()

    # Initialise sensor registry ---------------------------------------------
    def _build_sensors(self):
        configs = [
            ("TEMP_01", "Temperature", "Living Room"),
            ("TEMP_02", "Temperature", "Bedroom"),
            ("TEMP_03", "Temperature", "Kitchen"),
            ("HUM_01",  "Humidity",    "Living Room"),
            ("HUM_02",  "Humidity",    "Bedroom"),
            ("HUM_03",  "Humidity",    "Kitchen"),
            ("PRESS_01","Pressure",    "Outdoor"),
        ]
        self.sensors: dict[str, SensorData] = {
            sid: SensorData(sid, typ, loc) for sid, typ, loc in configs
        }

    # ────────────────────────────────────────────────────────────────── UI ──
    def _build_ui(self):
        tk.Label(self.root, text="Home Control Center", bg=APP_BG, fg="white",
                 font=("Arial", 18, "bold")).pack(pady=4)

        # status bar
        status_fr = tk.Frame(self.root, bg=APP_BG)
        status_fr.pack(fill="x")
        self.status_lbl = tk.Label(status_fr, text="Status: Initialising...",
                                   bg=APP_BG, fg="#ecf0f1")
        self.status_lbl.pack(side="left")
        self.time_lbl = tk.Label(status_fr, bg=APP_BG, fg="#ecf0f1")
        self.time_lbl.pack(side="right")

        # scrollable sensor grid
        canvas = tk.Canvas(self.root, bg=APP_BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(self.root, orient="vertical",
                                command=canvas.yview)
        self.scroll_fr = tk.Frame(canvas, bg=APP_BG)
        self.scroll_fr.bind("<Configure>",
                            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_fr, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        vscroll.pack(side="right", fill="y")

        self._populate_sensor_cards()
        self._schedule_gui_refresh()

    def _populate_sensor_cards(self):
        groups = {
            "🌡️ Temperature": (TEMP_CLR, [s for s in self.sensors.values() if s.sensor_type == "Temperature"]),
            "💧 Humidity":     (HUM_CLR,  [s for s in self.sensors.values() if s.sensor_type == "Humidity"]),
            "🌪️ Pressure":    (PRES_CLR, [s for s in self.sensors.values() if s.sensor_type == "Pressure"]),
        }
        for title, (clr, items) in groups.items():
            if not items:
                continue
            sec = tk.Frame(self.scroll_fr, bg=CARD_BG, bd=2, relief="raised")
            sec.pack(fill="x", pady=4)
            tk.Label(sec, text=title, bg=CARD_BG, fg="white",
                     font=("Arial", 14, "bold")).pack(pady=3)

            grid = tk.Frame(sec, bg=CARD_BG); grid.pack(padx=6, pady=4)
            for i, sensor in enumerate(items):
                row, col = divmod(i, 2)
                card = tk.Frame(grid, bg=clr, bd=2, relief="raised")
                card.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
                grid.grid_columnconfigure(col, weight=1)

                tk.Label(card, text=sensor.location, bg=clr, fg="white",
                         font=("Arial", 10, "bold")).pack(pady=1)
                val_lbl = tk.Label(card, text="--", bg=clr, fg="white",
                                   font=("Arial", 16, "bold"))
                val_lbl.pack()
                upd_lbl = tk.Label(card, text="No data", bg=clr, fg="#ecf0f1",
                                   font=("Arial", 8))
                upd_lbl.pack(pady=1)

                sensor.value_label, sensor.update_label = val_lbl, upd_lbl
                for w in (card, val_lbl):
                    w.bind("<Button-1>",
                           lambda e, s=sensor: SensorHistoryWindow(self.root, s))
                    w.bind("<Enter>", lambda e, f=card: f.configure(relief="sunken"))
                    w.bind("<Leave>", lambda e, f=card: f.configure(relief="raised"))

    # ───────────────────────────────────────────────────────── Threads / data
    def _start_threads(self):
        bt_th = threading.Thread(target=self._bluetooth.start_communication,
                                 daemon=True)
        bt_th.start(); self._threads.append(bt_th)
        # queue-pump stays in Tk thread via after()

    def _pump_queue(self):
        try:
            while True:
                data = self.data_q.get_nowait()
                sid, val = data.get("sensor_id"), data.get("value")
                if sid in self.sensors:
                    self.sensors[sid].add_data(val)
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self._pump_queue)

    # ───────────────────────────────────────────────────── GUI periodic refresh
    def _schedule_gui_refresh(self):
        if not self.running:
            return
        self._update_time()
        self._update_sensor_cards()
        self._update_status_bar()
        self.root.after(REFRESH_GUI_MS, self._schedule_gui_refresh)

    def _update_time(self):
        self.time_lbl.config(text=datetime.now().strftime("%H:%M:%S"))

    def _update_sensor_cards(self):
        for sensor in self.sensors.values():
            if not sensor.value_label:
                continue
            if sensor.current_value is None:
                sensor.value_label.config(text="--")
                sensor.update_label.config(text="No data")
                continue
            unit = UNITS.get(sensor.sensor_type, "")
            sensor.value_label.config(text=f"{sensor.current_value}{unit}")

            delta = datetime.now() - sensor.last_update
            if delta.total_seconds() < 60:
                txt = "Just now"
            elif delta.total_seconds() < 3600:
                txt = f"{int(delta.total_seconds() // 60)} m ago"
            else:
                txt = f"{int(delta.total_seconds() // 3600)} h ago"
            sensor.update_label.config(text=txt)

    def _update_status_bar(self):
        active = sum(1 for s in self.sensors.values() if s.current_value is not None)
        self.status_lbl.config(text=f"Status: {active}/{len(self.sensors)} sensors active")

    # ───────────────────────────────────────────────────────────── Demo feeder
    def _start_demo_data(self):
        def demo():
            while self.running:
                for s in self.sensors.values():
                    if "TEMP" in s.sensor_id:
                        base = 20 + random.randint(0, 5)
                        val = base + random.uniform(-2, 2)
                    elif "HUM" in s.sensor_id:
                        base = 45 + random.randint(0, 15)
                        val = base + random.uniform(-5, 5)
                    else:
                        val = 1013 + random.uniform(-10, 10)
                    s.add_data(round(val, 1))
                time.sleep(2)
        th = threading.Thread(target=demo, daemon=True)
        th.start(); self._threads.append(th)

    # ───────────────────────────────────────────────────────────── Shutdown
    def _on_close(self):
        self.running = False
        if hasattr(self._bluetooth, "stop"):
            try:
                self._bluetooth.stop()
            except Exception:
                pass
        self.root.destroy()

    # ───────────────────────────────────────────────────────────── Entrypoint
    def run(self):
        # first call after-based loops
        self.root.after(100, self._pump_queue)
        self.root.mainloop()

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    HomeAutomationGUI().run()
