#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, AppIndicator3, GLib
import subprocess

SERVICE = "mitmdump-antigravity.service"
LOGFILE = "/tmp/mitmdump.log"
MODEFILE = "/tmp/mitmdump-mode.status"

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def is_active():
    return run(f"systemctl --user is-active {SERVICE}") == "active"

def current_mode():
    mode = run(f"cat {MODEFILE} 2>/dev/null")
    if mode == "college":
        return "College (via corp proxy)"
    elif mode == "direct":
        return "Direct (hotspot/home)"
    return "Unknown"

class Tray:
    def __init__(self):
        self.ind = AppIndicator3.Indicator.new(
            "antigravity-proxy",
            "network-transmit-receive",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.menu = Gtk.Menu()

        self.status_item = Gtk.MenuItem(label="Status: checking...")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        self.mode_item = Gtk.MenuItem(label="Mode: checking...")
        self.mode_item.set_sensitive(False)
        self.menu.append(self.mode_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        restart_item = Gtk.MenuItem(label="Restart Proxy Service")
        restart_item.connect("activate", self.restart_service)
        self.menu.append(restart_item)

        launch_item = Gtk.MenuItem(label="Launch Antigravity")
        launch_item.connect("activate", self.launch_antigravity)
        self.menu.append(launch_item)

        logs_item = Gtk.MenuItem(label="View Logs")
        logs_item.connect("activate", self.view_logs)
        self.menu.append(logs_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit Tray")
        quit_item.connect("activate", self.quit)
        self.menu.append(quit_item)

        self.menu.show_all()
        self.ind.set_menu(self.menu)

        GLib.timeout_add_seconds(5, self.update_status)
        self.update_status()

    def update_status(self):
        active = is_active()
        self.status_item.set_label(f"Service: {'🟢 Running' if active else '🔴 Stopped'}")
        self.mode_item.set_label(f"Mode: {current_mode()}")
        return True

    def restart_service(self, _):
        run(f"systemctl --user restart {SERVICE}")
        self.update_status()

    def launch_antigravity(self, _):
        subprocess.Popen(["antigravity-launch"])

    def view_logs(self, _):
        subprocess.Popen(["x-terminal-emulator", "-e", f"tail -f {LOGFILE}"])

    def quit(self, _):
        Gtk.main_quit()

if __name__ == "__main__":
    Tray()
    Gtk.main()
