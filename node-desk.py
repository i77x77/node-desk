#!/usr/bin/python3
"""Node Desk desktop client for SSH and Tailscale on Linux and macOS."""
import ipaddress
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import sys
if sys.platform.startswith("linux"):
    sys.path.append("/usr/lib/node-desk")
import tkinter as tk
from tkinter import ttk, messagebox

from platform_support import config_dir, tailscale_binary

DEFAULT_IP = '100.114.10.75'


def validate_ip(value):
    value = value.strip()
    if '%' in value:
        raise ValueError('Укажите IP без идентификатора интерфейса.')
    return str(ipaddress.ip_address(value))


def describe_status(data):
    state = data.get('BackendState', 'Unknown')
    if state != 'Running':
        names = {'Stopped': 'Tailscale выключен', 'NeedsLogin': 'Нужен вход в Tailscale',
                 'NeedsMachineAuth': 'Устройство ожидает одобрения', 'Starting': 'Tailscale запускается'}
        return names.get(state, 'Tailscale: ' + state), '', '#f2ba6a'
    node = data.get('ExitNodeStatus')
    if not node:
        node = next((p for p in (data.get('Peer') or {}).values() if p.get('ExitNode')), None)
    if not node:
        return 'Не подключён', 'Exit node не используется', '#64748b'
    ips = ', '.join(str(ip).split('/')[0] for ip in node.get('TailscaleIPs', []))
    if not node.get('Online', False):
        return 'Узел недоступен', 'Выбран exit node: ' + (ips or node.get('ID', 'неизвестен')), '#f2ba6a'
    return 'Подключён', 'Exit node: ' + (ips or node.get('ID', 'неизвестен')), '#63d9a0'


def run_cli(args, privileged=False):
    binary = tailscale_binary()
    if not binary:
        raise RuntimeError('Tailscale не установлен. Установите его с tailscale.com/download.')
    command = [os.path.realpath(binary), *args]
    env = os.environ.copy()
    if sys.platform == 'darwin':
        env['TAILSCALE_BE_CLI'] = '1'
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=10, env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Время ожидания истекло. Проверьте статус: команда могла уже примениться.') from None
    if result.returncode:
        if privileged and any(word in (result.stderr or '').lower() for word in
                              ('access denied', 'permission denied', 'must be root', 'use sudo', 'not allowed')):
            if sys.platform == 'darwin':
                raise RuntimeError('Нет прав управления Tailscale. Откройте приложение Tailscale, '
                                   'войдите в сеть и проверьте разрешения.\n' + result.stderr.strip())
            raise RuntimeError('Нет прав управления Tailscale. Выполните один раз в терминале:\n'
                               'sudo tailscale set --operator="$USER"\n'
                               'Это разрешит вашему пользователю управлять Tailscale без пароля.')
        raise RuntimeError((result.stderr or result.stdout).strip() or 'Ошибка Tailscale')
    return result.stdout


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.polling = False
        self.closed = False
        self.selected = False
        self.known = False
        self.config = config_dir() / 'config.json'
        saved = DEFAULT_IP
        try:
            saved = validate_ip(json.loads(self.config.read_text()).get('ip', DEFAULT_IP))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        root.title('Node Desk')
        root.geometry('900x760')
        root.minsize(800, 720)
        root.configure(bg='#0d111b')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background='#0d111b', foreground='#e6edf7', font=('Sans', 11), bordercolor='#293247', lightcolor='#293247', darkcolor='#293247')
        style.configure('TFrame', background='#0d111b')
        style.configure('Card.TFrame', background='#171e2d')
        style.configure('TLabel', background='#0d111b', foreground='#e6edf7')
        style.configure('Muted.TLabel', foreground='#94a3bb', font=('Sans', 10))
        style.configure('Card.TLabel', background='#171e2d', foreground='#e6edf7')
        style.configure('CardMuted.TLabel', background='#171e2d', foreground='#94a3bb', font=('Sans', 10))
        style.configure('TEntry', padding=12, fieldbackground='#0f1522', foreground='#e6edf7', insertcolor='#e6edf7', bordercolor='#293247', lightcolor='#293247', darkcolor='#293247')
        style.map('TEntry', bordercolor=[('focus', '#668aff')], fieldbackground=[('disabled', '#171e2d')], foreground=[('disabled', '#64748b')])
        style.configure('Save.TButton', font=('Sans', 10, 'bold'), padding=(16, 11), background='#273249', foreground='#e6edf7', borderwidth=0)
        style.map('Save.TButton', background=[('active', '#344361')], foreground=[('disabled', '#64748b')])
        style.configure('Action.TButton', font=('Sans', 11, 'bold'), padding=(20, 13), background='#668aff', foreground='#081126', borderwidth=0)
        style.map('Action.TButton', background=[('disabled', '#293247'), ('active', '#8aa5ff')], foreground=[('disabled', '#64748b')])
        style.configure('SmallAction.TButton', font=('Sans', 10, 'bold'), padding=(16, 12), background='#668aff', foreground='#081126', borderwidth=0)
        style.map('SmallAction.TButton', background=[('active', '#8aa5ff')])
        style.configure('Link.TButton', background='#171e2d', foreground='#a8bdff', borderwidth=0, padding=(0, 4), font=('Sans', 10))
        style.map('Link.TButton', background=[('active', '#171e2d')], foreground=[('active', '#d0dcff')])
        style.configure('Danger.TButton', background='#34202b', foreground='#ff9eab', padding=(16, 13), borderwidth=0, font=('Sans', 10, 'bold'))
        style.map('Danger.TButton', background=[('active', '#4a2938')])
        style.configure('Vertical.TScrollbar', background='#293247', troughcolor='#0d111b', borderwidth=0, arrowsize=12)
        style.configure('Nav.TFrame', background='#171e2d')
        style.layout('Nav.TButton', [('Button.padding', {'sticky': 'nswe', 'children': [('Button.label', {'sticky': 'nswe'})]})])
        style.configure('Nav.TButton', background='#171e2d', foreground='#94a3bb', padding=(22, 12), font=('Sans', 11, 'bold'), anchor='center')
        style.map('Nav.TButton', background=[('active', '#202b40')], foreground=[('active', '#e6edf7')])
        style.configure('Selected.Nav.TButton', background='#2a3c64', foreground='#cbd9ff')
        style.map('Selected.Nav.TButton', background=[('active', '#334a78')], foreground=[('active', '#e6edff')])
        style.configure('Pages.TNotebook', background='#0d111b', borderwidth=0, tabmargins=0)
        style.layout('Pages.TNotebook.Tab', [])
        header = ttk.Frame(root, padding=(32, 22, 32, 18))
        header.pack(fill='x')
        brand = ttk.Frame(header)
        brand.pack(side='left')
        tk.Label(brand, text='N', bg='#668aff', fg='#0d111b', font=('Sans', 14, 'bold'), padx=9, pady=3).pack(side='left', padx=(0, 12))
        ttk.Label(brand, text='Node Desk', font=('Sans', 17, 'bold')).pack(side='left')
        navigation = ttk.Frame(header, style='Nav.TFrame', padding=4)
        navigation.pack(side='right')
        tk.Frame(root, height=1, bg='#20293a').pack(fill='x', padx=32)
        from ssh_client import SSHFrame
        tabs = ttk.Notebook(root, style='Pages.TNotebook')
        tabs.pack(fill='both', expand=True, padx=8, pady=(8, 12))
        frame = ttk.Frame(tabs, padding=26)
        tabs.add(frame, text='Tailscale')
        self.ssh_tab = SSHFrame(tabs)
        tabs.add(self.ssh_tab, text='Серверы')
        tabs.insert(0, self.ssh_tab)
        self.nav_buttons = []
        for page, label in ((self.ssh_tab, 'Серверы'), (frame, 'Tailscale')):
            button = ttk.Button(navigation, text=label, style='Nav.TButton', width=11,
                                command=lambda selected=page: tabs.select(selected))
            button.pack(side='left', padx=2)
            self.nav_buttons.append((str(page), button))
        self.tabs = tabs
        tabs.bind('<<NotebookTabChanged>>', lambda event: self.update_navigation())
        tabs.enable_traversal()
        tabs.select(self.ssh_tab)
        self.update_navigation()
        heading = ttk.Frame(frame)
        heading.pack(fill='x', pady=(0, 22))
        ttk.Label(heading, text='Tailscale', font=('Sans', 22, 'bold')).pack(side='left')
        ttk.Label(heading, text='EXIT NODE', foreground='#94a3bb', font=('Sans', 9, 'bold')).pack(side='right', pady=(9, 0))
        card = ttk.Frame(frame, style='Card.TFrame', padding=20)
        card.pack(fill='both', expand=True)
        status_row = ttk.Frame(card, style='Card.TFrame')
        status_row.pack(fill='x')
        self.dot = tk.Canvas(status_row, width=16, height=20, bg='#171e2d', highlightthickness=0)
        self.dot.pack(side='left', padx=(0, 8))
        self.light = self.dot.create_oval(3, 6, 11, 14, fill='#94a3b8', outline='')
        self.status = ttk.Label(status_row, text='Проверка…', style='Card.TLabel', font=('Sans', 15, 'bold'))
        self.status.pack(side='left')
        self.detail = ttk.Label(card, text='', style='Card.TLabel', foreground='#94a3bb', wraplength=390, font=('Sans', 9))
        self.detail.pack(anchor='w', pady=(5, 22))
        ttk.Label(card, text='IP узла', style='Card.TLabel', foreground='#94a3bb', font=('Sans', 10)).pack(anchor='w')
        row = ttk.Frame(card, style='Card.TFrame')
        row.pack(fill='x', pady=(8, 20))
        self.ip = tk.StringVar(value=saved)
        self.entry = ttk.Entry(row, textvariable=self.ip, font=('Sans', 12), width=20)
        self.entry.pack(side='left', fill='x', expand=True)
        self.save = ttk.Button(row, text='Сохранить', style='Save.TButton', command=self.save_ip)
        self.save.pack(side='right', padx=(10, 0))
        self.entry.bind('<Return>', lambda event: self.save_ip())
        self.toggle = ttk.Button(card, text='Подключить', style='Action.TButton', command=self.toggle_connection, state='disabled')
        self.toggle.pack(fill='x')
        self.note = ttk.Label(frame, text='', foreground='#94a3bb', font=('Sans', 9), wraplength=440)
        self.note.pack(anchor='w', pady=(12, 0))
        self.ip.trace_add('write', lambda *_: self.note.configure(text=''))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.drain)
        self.refresh()

    def update_navigation(self):
        selected = self.tabs.select()
        for page, button in self.nav_buttons:
            button.configure(style='Selected.Nav.TButton' if page == selected else 'Nav.TButton')

    def save_ip(self):
        try:
            address = validate_ip(self.ip.get())
            self.config.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config.with_suffix('.tmp')
            temporary.write_text(json.dumps({'ip': address}) + '\n')
            temporary.replace(self.config)
        except ValueError:
            messagebox.showerror('Некорректный IP', 'Введите корректный IPv4 или IPv6 адрес.', parent=self.root)
            return
        except OSError as exc:
            messagebox.showerror('Ошибка сохранения', str(exc), parent=self.root)
            return
        self.ip.set(address)
        self.note.configure(text='IP сохранён', foreground='#63d9a0')

    def close(self):
        ssh_tab = getattr(self, 'ssh_tab', None)
        if ssh_tab is not None and not ssh_tab.confirm_close():
            return
        try:
            address = validate_ip(self.ip.get())
        except ValueError:
            address = None
        if address:
            try:
                self.config.parent.mkdir(parents=True, exist_ok=True)
                self.config.write_text(json.dumps({'ip': address}) + '\n')
            except OSError as exc:
                messagebox.showerror('Ошибка сохранения IP', str(exc), parent=self.root)
                return
        self.closed = True
        self.root.destroy()

    def sync_button(self):
        self.toggle.configure(text=('Подключение…' if self.target_connect else 'Отключение…') if self.busy
                              else ('Отключить' if self.selected else 'Подключить'),
                              state='normal' if self.known and not self.busy else 'disabled')

    def toggle_connection(self):
        if self.known and not self.busy:
            self.change(not self.selected)

    def poll(self):
        if self.polling or self.busy:
            return
        self.polling = True
        def worker():
            try:
                data = json.loads(run_cli(['status', '--json']))
                if not isinstance(data, dict):
                    raise ValueError('Некорректный ответ Tailscale')
                self.events.put(('status', data))
            except Exception as exc:
                self.events.put(('status_error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self.poll()
        self.root.after(3000, self.refresh)

    def change(self, connect):
        if self.busy:
            return
        try:
            address = validate_ip(self.ip.get()) if connect else ''
        except ValueError:
            messagebox.showerror('Некорректный IP', 'Введите корректный IPv4 или IPv6 адрес.', parent=self.root)
            return
        self.busy = True
        self.target_connect = connect
        self.sync_button()
        for widget in (self.save, self.entry):
            widget.configure(state='disabled')
        self.note.configure(text='')
        def worker():
            try:
                run_cli(['set', '--exit-node=' + address], privileged=True)
                self.events.put(('done', ''))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def drain(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind in ('status', 'status_error'):
                    self.polling = False
                    if self.busy:
                        continue
                    if kind == 'status':
                        self.known = True
                        self.selected = bool(value.get('ExitNodeStatus') or any(
                            p.get('ExitNode') for p in (value.get('Peer') or {}).values()))
                        title, detail, color = describe_status(value)
                        self.status.configure(text=title)
                        self.dot.itemconfigure(self.light, fill=color)
                        self.detail.configure(text=detail if self.selected else '')
                        health = value.get('Health') or []
                        if health:
                            self.detail.configure(text='Есть предупреждения Tailscale')
                    else:
                        self.known = False
                        self.status.configure(text='Статус недоступен')
                        self.dot.itemconfigure(self.light, fill='#d97706')
                        self.detail.configure(text='Проверьте службу Tailscale')
                    self.sync_button()
                else:
                    self.busy = False
                    self.known = False
                    for widget in (self.save, self.entry):
                        widget.configure(state='normal')
                    self.sync_button()
                    if kind == 'error':
                        messagebox.showerror('Ошибка подключения', value, parent=self.root)
                    self.status.configure(text='Проверка…')
                    self.detail.configure(text='')
                    self.dot.itemconfigure(self.light, fill='#94a3b8')
                    self.poll()
        except queue.Empty:
            pass
        self.root.after(100, self.drain)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--smoke-test':
        # Never run the CI fixture against a user's real server list.
        if not os.environ.get('NODE_DESK_CONFIG_DIR'):
            raise SystemExit('Smoke test requires NODE_DESK_CONFIG_DIR pointing to a temporary folder.')
        output = Path(sys.argv[2])
        root = tk.Tk()
        App.refresh = lambda self: None
        app = App(root)
        root.update()
        from ssh_client import credentials
        app.ssh_tab.store.save(None, 'Smoke test', 'Temporary build verification', credentials('192.0.2.1', 'test', 22))
        app.ssh_tab.show_list()
        root.update()
        for page in app.tabs.tabs():
            app.tabs.select(page)
            root.update()
        app.ssh_tab.edit()
        root.update()
        app.ssh_tab.show_list()
        root.update()
        output.write_text(json.dumps({'ok': True, 'tabs': len(app.tabs.tabs()), 'platform': sys.platform}))
        root.destroy()
    else:
        App(tk.Tk()).root.mainloop()
