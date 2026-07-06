import os
import shutil
import time
import psutil
import socket
import subprocess
from typing import List, Dict
from fastapi import UploadFile
import config

class SystemOps:
    def get_system_stats(self) -> dict:
        cpu_temp = "N/A"
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                cpu_temp = round(int(f.read()) / 1000, 1)
        except:
            try:
                temps = psutil.sensors_temperatures()
                if 'cpu_thermal' in temps: cpu_temp = temps['cpu_thermal'][0].current
                elif 'coretemp' in temps: cpu_temp = temps['coretemp'][0].current
            except: pass

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net_stats = psutil.net_io_counters(pernic=True)
        wan_stats = net_stats.get(config.WAN_INTERFACE)
        
        rx_bytes = wan_stats.bytes_recv if wan_stats else 0
        tx_bytes = wan_stats.bytes_sent if wan_stats else 0

        interfaces = {}
        for iface, stats in net_stats.items():
            if iface != "lo" and not iface.startswith("br") and not iface.startswith("wlan"):
                interfaces[iface] = {
                    "rx_bytes": stats.bytes_recv,
                    "tx_bytes": stats.bytes_sent
                }

        try:
            boot_time = psutil.boot_time()
            seconds = time.time() - boot_time
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            uptime_str = f"{int(d)}d {int(h)}h {int(m)}m" if d > 0 else f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)} min"
        except:
            uptime_str = "Unknown"

        ip_list = []
        try:
            interfaces_ips = psutil.net_if_addrs()
            for iface_name, iface_addrs in interfaces_ips.items():
                for addr in iface_addrs:
                    if addr.family == socket.AF_INET and not iface_name.startswith("lo"):
                        ip_list.append(addr.address)
        except: ip_list = ["Error"]

        return {
            "cpu": psutil.cpu_percent(interval=None), "temp": cpu_temp,
            "ram": mem.percent, "ram_used": round(mem.used / (1024**3), 2),
            "ram_total": round(mem.total / (1024**3), 2),
            "disk": disk.percent, "disk_free": round(disk.free / (1024**3), 2),
            "uptime": uptime_str, "ips": "\n".join(ip_list),
            "wan_iface": config.WAN_INTERFACE,
            "wan_rx_total": rx_bytes, "wan_tx_total": tx_bytes,
            "interfaces": interfaces
        }

    def reboot_device(self):
        subprocess.run(["sudo", "reboot"])

    def get_system_logs(self, limit=150) -> list:
        logs = []
        if os.path.exists("system.log"):
            try:
                with open("system.log", "r") as f:
                    lines = f.readlines()
                    for line in lines[-limit:]:
                        line = line.strip()
                        if not line: continue
                        if line.startswith("[") and "]" in line:
                            split_idx = line.find("]")
                            logs.append({"timestamp": line[1:split_idx], "message": line[split_idx+1:].strip()})
                        else:
                            logs.append({"timestamp": "--", "message": line})
                    logs.reverse()
            except: pass
        return logs

    # --- File Management Helpers ---
    def get_banners(self, config_order: list) -> list:
        banner_files = []
        if os.path.exists("static/banners/set"):
            actual_files = os.listdir("static/banners/set")
            for f in config_order:
                if f in actual_files: banner_files.append(f)
            for f in actual_files:
                if f not in banner_files: banner_files.append(f)
        return banner_files

    def get_sounds(self) -> list:
        if os.path.exists("static/sounds"):
            return [f for f in os.listdir("static/sounds") if f.lower().endswith(('.mp3', '.wav', '.ogg'))]
        return []