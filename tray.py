#!/usr/bin/env python3
# ==============================================================================
# fut-bin — Bandeja do Sistema (StatusNotifierItem / System Tray)
# ==============================================================================
import ctypes
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Configura o nome do processo no kernel Linux e no Python
try:
    import setproctitle
    setproctitle.setproctitle("fut-bin")
except Exception:
    pass

try:
    libc = ctypes.CDLL("libc.so.6")
    libc.prctl(15, b"fut-bin", 0, 0, 0)
except Exception:
    pass

APP_ID = "fut-bin"
APP_NAME = "fut-bin"
SCRIPT_PATH = str(Path(__file__).resolve())
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Adiciona o site-packages do .venv se existir
VENV_SITE = SCRIPT_DIR / ".venv" / "lib" / "python3.12" / "site-packages"
if VENV_SITE.exists() and str(VENV_SITE) not in sys.path:
    sys.path.insert(0, str(VENV_SITE))

DATA_DIR = Path.home() / ".local" / "share" / "fut-bin"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TRAY_PID_FILE = DATA_DIR / "tray.pid"
SERVER_PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "fut-bin.log"

ICON_PATH = SCRIPT_DIR / "web" / "icon.png"
if not ICON_PATH.exists():
    ICON_PATH = SCRIPT_DIR / "icon.png"
if not ICON_PATH.exists():
    ICON_PATH = Path.home() / ".local" / "share" / "icons" / "fut-bin.png"


def ensure_hicolor_icons():
    """Garante que os ícones do fut-bin estejam instalados em todos os tamanhos hicolor."""
    if not ICON_PATH.exists():
        return
    try:
        from PIL import Image
        base = Path.home() / ".local" / "share" / "icons" / "hicolor"
        img = Image.open(str(ICON_PATH))
        sizes = [16, 22, 24, 32, 48, 64, 128, 256, 512]
        updated = False

        for s in sizes:
            for cat in ("apps", "status"):
                target_dir = base / f"{s}x{s}" / cat
                target_file = target_dir / "fut-bin.png"
                if not target_file.exists():
                    target_dir.mkdir(parents=True, exist_ok=True)
                    img.resize((s, s), Image.Resampling.LANCZOS).save(target_file)
                    updated = True

        if updated:
            subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(base)], check=False)
    except Exception:
        pass


def notify(title: str, msg: str):
    """Envia notificação nativa da área de trabalho do Linux com o ícone do fut-bin."""
    try:
        subprocess.Popen(
            ["notify-send", "-a", "fut-bin", "-i", "fut-bin", title, msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def is_server_running(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """Verifica se o servidor FastAPI/Uvicorn (8000) está respondendo."""
    try:
        req = urllib.request.Request(f"http://{host}:{port}/")
        with urllib.request.urlopen(req, timeout=1.5) as res:
            return res.status in (200, 302, 307)
    except Exception:
        return False


BROWSER_NAMES = (
    "brave", "chrome", "google-chrome", "chromium", "firefox", "opera",
    "msedge", "edge", "epiphany", "zen", "vivaldi", "waterfox", "tor"
)


def is_safe_to_kill(pid: int) -> bool:
    """Validação rigorosa: NUNCA finalizar navegadores ou outros aplicativos do usuário.
    Retorna True SOMENTE se o processo for comprovadamente o servidor ou daemon do fut-bin."""
    if pid <= 1 or pid == os.getpid():
        return False
    try:
        proc_dir = Path(f"/proc/{pid}")
        if not proc_dir.exists():
            return False

        # Verifica comm
        comm_path = proc_dir / "comm"
        comm = comm_path.read_text("utf-8", "ignore").strip().lower() if comm_path.exists() else ""

        # Verifica cmdline
        cmd_path = proc_dir / "cmdline"
        cmd = cmd_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore").lower() if cmd_path.exists() else ""

        # PROTEÇÃO ABSOLUTA: se for qualquer navegador web, NUNCA toca
        for b in BROWSER_NAMES:
            if b in comm or b in cmd:
                return False

        # Processos pertencentes ao fut-bin
        is_futbin_dir = str(SCRIPT_DIR).lower() in cmd
        is_futbin_cmd = any(k in cmd for k in ["assistente_web.py", "assistente_web:app", "fut-bin"])
        is_tray = "tray.py" in cmd or comm == "fut-bin"

        return (is_futbin_dir and is_futbin_cmd) or is_tray
    except Exception:
        return False


def get_futbin_pids() -> list[int]:
    """Retorna lista de PIDs de processos pertencentes EXCLUSIVAMENTE ao servidor do fut-bin."""
    pids = set()
    my_pid = os.getpid()

    # 1. PID do servidor salvo no arquivo SERVER_PID_FILE e seus filhos diretos
    if SERVER_PID_FILE.exists():
        try:
            spid = int(SERVER_PID_FILE.read_text().strip())
            if spid != my_pid and is_safe_to_kill(spid):
                pids.add(spid)
                try:
                    out = subprocess.check_output(["pgrep", "-P", str(spid)], stderr=subprocess.DEVNULL)
                    for line in out.decode().strip().split("\n"):
                        if line.strip():
                            cpid = int(line.strip())
                            if is_safe_to_kill(cpid):
                                pids.add(cpid)
                except Exception:
                    pass
        except Exception:
            pass

    # 2. Processo ouvindo na porta 8000
    try:
        out = subprocess.check_output(["lsof", "-t", "-sTCP:LISTEN", "-i:8000"], stderr=subprocess.DEVNULL)
        for line in out.decode().strip().split("\n"):
            if line.strip():
                pid = int(line.strip())
                if pid != my_pid and is_safe_to_kill(pid):
                    pids.add(pid)
    except Exception:
        pass

    # 3. Processo executando assistente_web.py no diretório
    try:
        out = subprocess.check_output(["pgrep", "-f", "assistente_web.py"], stderr=subprocess.DEVNULL)
        for line in out.decode().strip().split("\n"):
            if line.strip():
                pid = int(line.strip())
                if pid != my_pid and is_safe_to_kill(pid):
                    pids.add(pid)
    except Exception:
        pass

    return sorted(list(pids))


def get_pid_memory_mb(pid: int) -> float:
    """Retorna o uso de memória RSS em megabytes para um determinado PID."""
    try:
        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            for line in status_path.read_text("utf-8", "ignore").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return float(parts[1]) / 1024.0

        statm_path = Path(f"/proc/{pid}/statm")
        if statm_path.exists():
            parts = statm_path.read_text().split()
            pages = int(parts[1])
            page_size = os.sysconf("SC_PAGE_SIZE")
            return (pages * page_size) / (1024.0 * 1024.0)
    except Exception:
        pass
    return 0.0


def get_memory_display(pids: list[int]) -> str:
    """Retorna representação textual amigável da memória total consumida."""
    total_mb = sum(get_pid_memory_mb(p) for p in pids if p > 0)
    if total_mb >= 1024.0:
        return f"{total_mb / 1024.0:.2f} GB"
    return f"{total_mb:.1f} MB"


def open_browser():
    """Abre o assistente do fut-bin no navegador padrão."""
    url = "http://127.0.0.1:8000"
    try:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass


def stop_server_processes():
    """Encerra com segurança absoluta os processos do servidor fut-bin."""
    pids = get_futbin_pids()
    if not pids:
        return

    # 1. SIGTERM suave
    for pid in pids:
        if is_safe_to_kill(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    # Aguarda até 2.5 segundos
    for _ in range(25):
        time.sleep(0.1)
        remaining = [p for p in pids if Path(f"/proc/{p}").exists()]
        if not remaining:
            break
    else:
        # 2. SIGKILL apenas para remanescentes comprovados
        for pid in remaining:
            if is_safe_to_kill(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

    if SERVER_PID_FILE.exists():
        SERVER_PID_FILE.unlink(missing_ok=True)


def start_server_process():
    """Inicia o servidor assistente_web do fut-bin em segundo plano."""
    if is_server_running():
        return None

    bin_path = Path.home() / ".local" / "bin" / "fut-bin"
    venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"

    if bin_path.exists() and os.access(bin_path, os.X_OK):
        cmd = [str(bin_path), "server"]
    elif venv_python.exists():
        cmd = [str(venv_python), str(SCRIPT_DIR / "assistente_web.py")]
    else:
        cmd = [sys.executable, str(SCRIPT_DIR / "assistente_web.py")]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if (SCRIPT_DIR / ".venv").exists():
        env["VIRTUAL_ENV"] = str(SCRIPT_DIR / ".venv")
        env["PATH"] = f"{SCRIPT_DIR}/.venv/bin:{env.get('PATH', '')}"

    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"\n--- [fut-bin] Iniciando servidor em {time.ctime()} ---\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(SCRIPT_DIR),
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    SERVER_PID_FILE.write_text(str(proc.pid))
    return proc


def is_tray_running() -> bool:
    """Verifica se o daemon da bandeja já está em execução."""
    if TRAY_PID_FILE.exists():
        try:
            pid = int(TRAY_PID_FILE.read_text().strip())
            if pid != os.getpid() and os.path.exists(f"/proc/{pid}"):
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().decode("utf-8", "ignore")
                with open(f"/proc/{pid}/comm", "rb") as f:
                    comm = f.read().decode("utf-8", "ignore").strip()
                if "fut-bin" in cmd or "tray.py" in cmd or comm == "fut-bin":
                    return True
        except Exception:
            pass
    return False


# ==============================================================================
# DAEMON DE BANDEJA (StatusNotifierItem / DBusMenu)
# ==============================================================================

def run_tray_daemon():
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib

    try:
        import setproctitle
        setproctitle.setproctitle("fut-bin")
    except Exception:
        pass

    ensure_hicolor_icons()

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()

    my_pid = os.getpid()
    TRAY_PID_FILE.write_text(str(my_pid))

    # Inicia servidor se não estiver rodando
    if not is_server_running():
        start_server_process()

    def get_icon_pixmaps():
        pixmaps = []
        if not ICON_PATH.exists():
            return pixmaps
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf

            for sz in (32, 24, 22, 16):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ICON_PATH), sz, sz, True)
                w = pixbuf.get_width()
                h = pixbuf.get_height()
                raw = pixbuf.get_pixels()
                has_alpha = pixbuf.get_has_alpha()
                rowstride = pixbuf.get_rowstride()
                n_channels = pixbuf.get_n_channels()

                argb = bytearray()
                for y in range(h):
                    row_offset = y * rowstride
                    for x in range(w):
                        px = row_offset + x * n_channels
                        r, g, b = raw[px], raw[px + 1], raw[px + 2]
                        a = raw[px + 3] if has_alpha else 255
                        argb.extend([a, r, g, b])
                pixmaps.append(dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(bytes(argb))), signature=None))
        except Exception as e:
            print(f"[fut-bin] Aviso ao processar pixmap: {e}")
        return pixmaps

    class FutBinDBusMenu(dbus.service.Object):
        def __init__(self, bus_conn, path, tray_obj):
            super().__init__(bus_conn, path)
            self.tray = tray_obj
            self.revision = 1

        @dbus.service.method("com.canonical.dbusmenu", in_signature="iias", out_signature="u(ia{sv}av)")
        def GetLayout(self, parent_id, recursion_depth, property_names):
            current_pid = os.getpid()
            server_pids = get_futbin_pids()
            is_running = is_server_running()
            status_label = "🟢 Servidor Ativo (porta 8000)" if is_running else "🔴 Servidor Inativo"
            pids_text = ", ".join(map(str, server_pids)) if server_pids else "nenhum"
            mem_text = get_memory_display([current_pid] + server_pids)

            items = [
                # Cabeçalho Informativo
                dbus.Struct((
                    dbus.Int32(10),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String(f"⚽ fut-bin (PID {current_pid})", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(False, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(11),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String(f"{status_label}", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(False, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(12),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String(f"📊 Memória: {mem_text} | Servidor PID: {pids_text}", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(False, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(13),
                    dbus.Dictionary({
                        dbus.String("type"): dbus.String("separator", variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                # Ações de Controle
                dbus.Struct((
                    dbus.Int32(1),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String("🌐 Abrir no Navegador", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(2),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String(f"📊 Detalhes de Processo e Memória", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(3),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String("🔄 Reiniciar Servidor", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(4),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String("⏹️ Parar Servidor" if is_running else "▶️ Iniciar Servidor", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(14),
                    dbus.Dictionary({
                        dbus.String("type"): dbus.String("separator", variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                # Finalização
                dbus.Struct((
                    dbus.Int32(5),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String("🛑 Fechar fut-bin (Servidor e Bandeja)", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
                dbus.Struct((
                    dbus.Int32(6),
                    dbus.Dictionary({
                        dbus.String("label"): dbus.String("⚡ Forçar Finalização (kill -9)", variant_level=1),
                        dbus.String("enabled"): dbus.Boolean(True, variant_level=1),
                    }, signature="sv"),
                    dbus.Array([], signature="v"),
                ), signature=None),
            ]

            root = dbus.Struct((
                dbus.Int32(0),
                dbus.Dictionary({"children-display": dbus.String("submenu", variant_level=1)}, signature="sv"),
                dbus.Array(items, signature="v"),
            ), signature=None)

            return (dbus.UInt32(self.revision), root)

        @dbus.service.method("com.canonical.dbusmenu", in_signature="i", out_signature="b")
        def AboutToShow(self, id_):
            return False

        @dbus.service.method("com.canonical.dbusmenu", in_signature="aias", out_signature="a(ia{sv})")
        def GetGroupProperties(self, ids, property_names):
            return dbus.Array([], signature="(ia{sv})")

        @dbus.service.method("com.canonical.dbusmenu", in_signature="isvu", out_signature="")
        def Event(self, id_, event_id, data, timestamp):
            if event_id == "clicked":
                if id_ == 1:
                    self.tray.open_browser()
                elif id_ == 2:
                    self.tray.show_status()
                elif id_ == 3:
                    self.tray.restart_server()
                elif id_ == 4:
                    self.tray.toggle_server()
                elif id_ == 5:
                    self.tray.quit_application()
                elif id_ == 6:
                    self.tray.force_kill_application()

        @dbus.service.signal("com.canonical.dbusmenu", signature="ui")
        def LayoutUpdated(self, revision, parent):
            pass

    class FutBinSNI(dbus.service.Object):
        def __init__(self, bus_conn, path, loop_obj):
            super().__init__(bus_conn, path)
            self.loop = loop_obj
            self.menu_obj = None
            self.cached_pixmap = dbus.Array([], signature="(iiay)")
            pixmaps = get_icon_pixmaps()
            if pixmaps:
                self.cached_pixmap = dbus.Array(pixmaps, signature=dbus.Signature("(iiay)"))

        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
        def Get(self, interface_name, property_name):
            props = self.GetAll(interface_name)
            if property_name in props:
                return props[property_name]
            raise dbus.exceptions.DBusException(
                f"Property '{property_name}' not found",
                name="org.freedesktop.DBus.Error.UnknownProperty",
            )

        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface_name):
            if interface_name == "org.kde.StatusNotifierItem":
                current_pid = os.getpid()
                server_pids = get_futbin_pids()
                is_running = is_server_running()
                status_str = "🟢 Ativo (http://localhost:8000)" if is_running else "🔴 Inativo"
                mem_str = get_memory_display([current_pid] + server_pids)
                all_pids = sorted(list(set([current_pid] + server_pids)))

                tooltip_text = (
                    f"⚽ fut-bin — Melhores Momentos\n"
                    f"Status: {status_str}\n"
                    f"Uso de Memória: {mem_str}\n"
                    f"Processos: fut-bin (PIDs: {all_pids})"
                )

                return dbus.Dictionary({
                    dbus.String("Category"): dbus.String("ApplicationStatus", variant_level=1),
                    dbus.String("Id"): dbus.String(APP_ID, variant_level=1),
                    dbus.String("Title"): dbus.String("fut-bin", variant_level=1),
                    dbus.String("Status"): dbus.String("Active", variant_level=1),
                    dbus.String("IconName"): dbus.String("fut-bin", variant_level=1),
                    dbus.String("IconPixmap"): self.cached_pixmap,
                    dbus.String("OverlayIconName"): dbus.String("", variant_level=1),
                    dbus.String("AttentionIconName"): dbus.String("", variant_level=1),
                    dbus.String("AttentionMovieName"): dbus.String("", variant_level=1),
                    dbus.String("IconThemePath"): dbus.String(str(Path.home() / ".local" / "share" / "icons" / "hicolor"), variant_level=1),
                    dbus.String("Menu"): dbus.ObjectPath("/org/futbin/sni/menu", variant_level=1),
                    dbus.String("ItemIsMenu"): dbus.Boolean(False, variant_level=1),
                    dbus.String("ToolTip"): dbus.Struct(
                        ("fut-bin", dbus.Array([], signature="(iiay)"), "fut-bin", tooltip_text),
                        signature=None,
                        variant_level=1,
                    ),
                }, signature="sv")
            return dbus.Dictionary({}, signature="sv")

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def Category(self):
            return "ApplicationStatus"

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def Id(self):
            return APP_ID

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def Title(self):
            return "fut-bin"

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def Status(self):
            return "Active"

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def IconName(self):
            return "fut-bin"

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="a(iiay)")
        def IconPixmap(self):
            return self.cached_pixmap

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def OverlayIconName(self):
            return ""

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def AttentionIconName(self):
            return ""

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def AttentionMovieName(self):
            return ""

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="s")
        def IconThemePath(self):
            return str(Path.home() / ".local" / "share" / "icons" / "hicolor")

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="o")
        def Menu(self):
            return dbus.ObjectPath("/org/futbin/sni/menu")

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="b")
        def ItemIsMenu(self):
            return False

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="", out_signature="(sa(iiay)ss)")
        def ToolTip(self):
            current_pid = os.getpid()
            server_pids = get_futbin_pids()
            is_running = is_server_running()
            status_str = "🟢 Ativo (http://localhost:8000)" if is_running else "🔴 Inativo"
            mem_str = get_memory_display([current_pid] + server_pids)
            all_pids = sorted(list(set([current_pid] + server_pids)))

            tooltip_text = (
                f"⚽ fut-bin — Melhores Momentos\n"
                f"Status: {status_str}\n"
                f"Uso de Memória: {mem_str}\n"
                f"Processos: fut-bin (PIDs: {all_pids})"
            )
            return ("fut-bin", dbus.Array([], signature="(iiay)"), "fut-bin", tooltip_text)

        @dbus.service.signal("org.kde.StatusNotifierItem", signature="")
        def NewToolTip(self):
            pass

        def show_gtk_popup(self, x=0, y=0):
            """Fallback com menu GTK3 nativo se o desktop chamar ContextMenu diretamente."""
            try:
                import gi
                gi.require_version("Gtk", "3.0")
                from gi.repository import Gtk
                Gtk.init_check()

                current_pid = os.getpid()
                server_pids = get_futbin_pids()
                is_running = is_server_running()
                mem_text = get_memory_display([current_pid] + server_pids)
                pids_text = ", ".join(map(str, server_pids)) if server_pids else "nenhum"
                status_label = "🟢 Servidor Ativo (:8000)" if is_running else "🔴 Servidor Inativo"

                menu = Gtk.Menu()

                header = Gtk.MenuItem(label=f"⚽ fut-bin (PID {current_pid})")
                header.set_sensitive(False)
                menu.append(header)

                subinfo = Gtk.MenuItem(label=f"{status_label} | Memória: {mem_text}")
                subinfo.set_sensitive(False)
                menu.append(subinfo)

                menu.append(Gtk.SeparatorMenuItem())

                item_open = Gtk.MenuItem(label="🌐 Abrir no Navegador")
                item_open.connect("activate", lambda _: self.open_browser())
                menu.append(item_open)

                item_status = Gtk.MenuItem(label=f"📊 Detalhes de Memória (PIDs: {pids_text})")
                item_status.connect("activate", lambda _: self.show_status())
                menu.append(item_status)

                item_restart = Gtk.MenuItem(label="🔄 Reiniciar Servidor")
                item_restart.connect("activate", lambda _: self.restart_server())
                menu.append(item_restart)

                item_toggle = Gtk.MenuItem(label="⏹️ Parar Servidor" if is_running else "▶️ Iniciar Servidor")
                item_toggle.connect("activate", lambda _: self.toggle_server())
                menu.append(item_toggle)

                menu.append(Gtk.SeparatorMenuItem())

                item_quit = Gtk.MenuItem(label="🛑 Fechar fut-bin (Servidor e Bandeja)")
                item_quit.connect("activate", lambda _: self.quit_application())
                menu.append(item_quit)

                item_force = Gtk.MenuItem(label="⚡ Forçar Finalização (kill -9)")
                item_force.connect("activate", lambda _: self.force_kill_application())
                menu.append(item_force)

                menu.show_all()
                menu.popup(None, None, None, None, 3, Gtk.get_current_event_time())
            except Exception:
                pass

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def ContextMenu(self, x, y):
            self.show_gtk_popup(x, y)

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def Activate(self, x, y):
            self.open_browser()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def SecondaryActivate(self, x, y):
            self.open_browser()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="is", out_signature="")
        def Scroll(self, delta, orientation):
            pass

        def open_browser(self):
            open_browser()

        def show_status(self):
            current_pid = os.getpid()
            running = is_server_running()
            server_pids = get_futbin_pids()
            all_pids = sorted(list(set([current_pid] + server_pids)))
            mem_text = get_memory_display(all_pids)
            if running:
                msg = (
                    f"🟢 Processo: fut-bin (PID {current_pid})\n"
                    f"• Web: http://127.0.0.1:8000\n"
                    f"• Memória Total: {mem_text}\n"
                    f"• PIDs Servidor: {server_pids}"
                )
            else:
                msg = f"🔴 Processo: fut-bin (PID {current_pid})\nServidor inativo. Memória: {mem_text}"
            notify("fut-bin", msg)

        def toggle_server(self):
            if is_server_running():
                notify("fut-bin", "⏹️ Parando servidor...")
                stop_server_processes()
                notify("fut-bin", "🔴 Servidor parado.")
            else:
                notify("fut-bin", "▶️ Iniciando servidor...")
                start_server_process()
                notify("fut-bin", "🟢 Servidor iniciado!")

        def restart_server(self):
            notify("fut-bin", "🔄 Reiniciando servidor fut-bin...")
            stop_server_processes()
            time.sleep(1)
            start_server_process()
            notify("fut-bin", "🟢 Servidor reiniciado com sucesso!")

        def quit_application(self):
            current_pid = os.getpid()
            notify("fut-bin", f"🛑 Fechando fut-bin (PID {current_pid}) e servidores...")
            stop_server_processes()
            if TRAY_PID_FILE.exists():
                TRAY_PID_FILE.unlink(missing_ok=True)
            self.loop.quit()

        def force_kill_application(self):
            notify("fut-bin", "⚡ Finalizando forçadamente (kill -9) todos os processos fut-bin...")
            pids = get_futbin_pids()
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
            if SERVER_PID_FILE.exists():
                SERVER_PID_FILE.unlink(missing_ok=True)
            if TRAY_PID_FILE.exists():
                TRAY_PID_FILE.unlink(missing_ok=True)
            self.loop.quit()
            os._exit(0)

    service_name = f"org.kde.StatusNotifierItem-{APP_ID}"
    dbus.service.BusName(service_name, bus)

    loop = GLib.MainLoop()
    sni = FutBinSNI(bus, "/org/futbin/sni", loop)
    menu = FutBinDBusMenu(bus, "/org/futbin/sni/menu", sni)
    sni.menu_obj = menu

    # Registra no StatusNotifierWatcher
    try:
        watcher = bus.get_object("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")
        watcher.RegisterStatusNotifierItem("/org/futbin/sni", dbus_interface="org.kde.StatusNotifierWatcher")
    except Exception as e:
        print(f"[fut-bin] Aviso ao registrar no StatusNotifierWatcher: {e}")

    # Atualização periódica da bandeja (a cada 3s) para memória e status em tempo real
    def periodic_status_update():
        try:
            menu.revision += 1
            menu.LayoutUpdated(menu.revision, 0)
            sni.NewToolTip()
        except Exception:
            pass
        return True

    GLib.timeout_add_seconds(3, periodic_status_update)

    def handle_signal(sig, frame):
        sni.quit_application()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    notify("fut-bin", f"⚽ Processo 'fut-bin' ativo na bandeja do sistema!")

    try:
        loop.run()
    except (KeyboardInterrupt, SystemExit):
        sni.quit_application()


# ==============================================================================
# COMANDOS CLI
# ==============================================================================

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "start"

    if action in ("stop", "kill"):
        print("🛑 Finalizando processo fut-bin e servidor...")
        if TRAY_PID_FILE.exists():
            try:
                tpid = int(TRAY_PID_FILE.read_text().strip())
                sig = signal.SIGKILL if action == "kill" else signal.SIGTERM
                if is_safe_to_kill(tpid):
                    os.kill(tpid, sig)
            except Exception:
                pass
            TRAY_PID_FILE.unlink(missing_ok=True)
        stop_server_processes()
        notify("fut-bin", "🛑 Processo fut-bin e servidor finalizados.")
        print("✅ Processo fut-bin finalizado com sucesso.")
        sys.exit(0)

    elif action == "restart":
        print("🔄 Reiniciando fut-bin...")
        stop_server_processes()
        time.sleep(1)
        start_server_process()
        notify("fut-bin", "🔄 Servidor reiniciado com sucesso!")
        print("✅ Servidor reiniciado.")
        sys.exit(0)

    elif action == "status":
        running = is_server_running()
        tray_active = is_tray_running()
        server_pids = get_futbin_pids()
        tray_pid = None
        if TRAY_PID_FILE.exists():
            try:
                tray_pid = int(TRAY_PID_FILE.read_text().strip())
            except Exception:
                pass
        all_pids = sorted(list(set(([tray_pid] if tray_pid else []) + server_pids)))
        mem_str = get_memory_display(all_pids)

        print("=== Status do Processo fut-bin ===")
        print(f"  Nome do Processo:   fut-bin {'(PID: ' + str(tray_pid) + ')' if tray_pid else ''}")
        print(f"  Bandeja do Sistema: {'🟢 Ativa (StatusNotifierItem)' if tray_active else '⚪ Inativa'}")
        print(f"  Servidor Web (8000): {'🟢 Ativo' if running else '🔴 Inativo'}")
        print(f"  PIDs Vinculados:    {all_pids}")
        print(f"  Memória Utilizada:  {mem_str}")
        sys.exit(0)

    elif action == "open":
        open_browser()
        sys.exit(0)

    elif action == "server":
        # Executa o servidor assistente_web diretamente neste processo com o título fut-bin
        try:
            import setproctitle
            setproctitle.setproctitle("fut-bin")
        except Exception:
            pass
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.prctl(15, b"fut-bin", 0, 0, 0)
        except Exception:
            pass

        SERVER_PID_FILE.write_text(str(os.getpid()))

        # Passa argumentos restantes para o assistente_web
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        import assistente_web
        assistente_web.main()

    elif action == "daemon":
        run_tray_daemon()

    elif action in ("start", "run", "tray"):
        if is_tray_running():
            print("⚡ Processo 'fut-bin' já está em execução na bandeja!")
            open_browser()
            sys.exit(0)

        print("🚀 Iniciando processo 'fut-bin' na bandeja do sistema...")
        bin_path = Path.home() / ".local" / "bin" / "fut-bin"
        if bin_path.exists() and os.access(bin_path, os.X_OK):
            cmd = [str(bin_path), "daemon"]
        else:
            cmd = [sys.executable or "/usr/bin/python3", SCRIPT_PATH, "daemon"]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(1.0)
        sys.exit(0)

    elif action == "site":
        open_browser()
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        import assistente_web
        assistente_web.main()

    elif (
        action.endswith(".py")
        or (SCRIPT_DIR / f"{action}.py").is_file()
        or (SCRIPT_DIR / action).is_file()
        or os.path.isfile(action)
        or action.startswith("-")
    ):
        venv_python = SCRIPT_DIR / ".venv" / "bin" / "python"
        import shutil
        py_bin = str(venv_python) if venv_python.exists() else (shutil.which("python3") or sys.executable)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if (SCRIPT_DIR / ".venv").exists():
            env["VIRTUAL_ENV"] = str(SCRIPT_DIR / ".venv")
            env["PATH"] = f"{SCRIPT_DIR}/.venv/bin:{env.get('PATH', '')}"

        if action.startswith("-"):
            args = [py_bin] + sys.argv[1:]
        else:
            if (SCRIPT_DIR / action).is_file():
                script_path = SCRIPT_DIR / action
            elif (SCRIPT_DIR / f"{action}.py").is_file():
                script_path = SCRIPT_DIR / f"{action}.py"
            else:
                script_path = Path(action).resolve()
            args = [py_bin, str(script_path)] + sys.argv[2:]

        try:
            os.execve(py_bin, args, env)
        except Exception:
            res = subprocess.run(args, env=env)
            sys.exit(res.returncode)

    else:
        print(f"Uso: {sys.argv[0]} [start|tray|stop|kill|restart|status|open|server|site|<script.py>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
