"""Philibert's tray icon: shown only when Philibert is still running but has no window it can
watch - it opened in the person's own browser (closing a tab tells Philibert nothing), or its
window is gone while the browser stays behind. Otherwise people believe it is closed while it
keeps running. Two items: Open Philibert, and Shut down.

Windows only. The icon is a small PowerShell NotifyIcon (Philibert already uses PowerShell for its
file dialogs, so nothing new is installed); it says what was clicked on its output, one word a line.

    tray = nd_tray.Tray(on_open, on_quit, icon=path)   # shows the icon
    tray.close()                                       # takes it away
(the icon also goes by itself when Philibert's process ends)
"""
import subprocess
import sys
import threading

_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$out = [Console]::Out
$n = New-Object System.Windows.Forms.NotifyIcon
try { $n.Icon = New-Object System.Drawing.Icon($env:ND_TRAY_ICON) } catch { $n.Icon = [System.Drawing.SystemIcons]::Application }
$n.Text = 'Philibert is running'
$m = New-Object System.Windows.Forms.ContextMenuStrip
$o = $m.Items.Add('Open Philibert'); $o.Font = New-Object System.Drawing.Font($o.Font, [System.Drawing.FontStyle]::Bold)
$o.Add_Click({ $out.WriteLine('open'); $out.Flush() })
[void]$m.Items.Add('-')
$q = $m.Items.Add('Shut down Philibert')
$q.Add_Click({ $out.WriteLine('quit'); $out.Flush(); $n.Visible = $false; [System.Windows.Forms.Application]::Exit() })
$n.ContextMenuStrip = $m
$n.Add_MouseDoubleClick({ $out.WriteLine('open'); $out.Flush() })
$n.Visible = $true
$n.ShowBalloonTip(8000, 'Philibert is still running', $env:ND_TRAY_SAY, [System.Windows.Forms.ToolTipIcon]::Info)
# gone with Philibert, even when it ends without taking the icon away (a crash)
$owner = [int]$env:ND_TRAY_OWNER
$t = New-Object System.Windows.Forms.Timer; $t.Interval = 1500
$t.Add_Tick({ if ((Test-Path $env:ND_TRAY_STOP) -or -not (Get-Process -Id $owner -ErrorAction SilentlyContinue)) { $n.Visible = $false; [System.Windows.Forms.Application]::Exit() } })
$t.Start()
[System.Windows.Forms.Application]::Run()
$n.Dispose()
"""


class Tray:
    def __init__(self, on_open, on_quit, icon="", say="", log=lambda m: None):
        self.proc = None
        if sys.platform != "win32":
            return
        import os
        import tempfile
        self.stop = os.path.join(tempfile.gettempdir(), f"philibert-tray-{os.getpid()}.stop")
        try:
            os.remove(self.stop)
        except OSError:
            pass
        env = {**os.environ, "ND_TRAY_ICON": str(icon or ""), "ND_TRAY_OWNER": str(os.getpid()), "ND_TRAY_STOP": self.stop,
               "ND_TRAY_SAY": say or "Right-click this icon to open Philibert again or to shut it down."}
        try:
            self.proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            log(f"tray icon: {e}")
            return

        def listen(p=self.proc):
            for line in p.stdout:
                word = line.strip()
                try:
                    if word == "open":
                        on_open()
                    elif word == "quit":
                        on_quit()
                        return
                except Exception as e:          # a click must never take Philibert down
                    log(f"tray icon: {e}")
        threading.Thread(target=listen, daemon=True).start()

    @property
    def shown(self):
        return bool(self.proc and self.proc.poll() is None)

    def close(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            import os
            try:
                open(self.stop, "w").close()      # the icon takes itself away (a killed one lingers until hovered)
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            try:
                os.remove(self.stop)
            except OSError:
                pass
