#!/usr/bin/python3
"""SSH UI and helper using platform credential stores."""
import json
import ipaddress
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import uuid
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from platform_support import config_dir

SERVICE = 'tailscale-exit-ui.ssh'


def credentials(host, user, port):
    host = str(ipaddress.ip_address(host.strip()))
    user = user.strip()
    if not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}', user):
        raise ValueError('Введите корректное имя пользователя SSH.')
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('Порт должен быть от 1 до 65535.')
    return {'host': host, 'user': user, 'port': port}


def identity(profile):
    return json.dumps(profile, sort_keys=True)


def vault():
    # Select explicitly: never fall back to a plaintext keyring backend.
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
    else:
        from keyring.backends.SecretService import Keyring
    return Keyring()


def ssh_command(profile):
    return ['ssh', '-o', 'StrictHostKeyChecking=ask', '-o', 'ConnectTimeout=15',
            '-o', 'NumberOfPasswordPrompts=1', '-p', str(profile['port']),
            '-l', profile['user'], '--', profile['host']]


def terminal_command(command):
    for name in ('x-terminal-emulator', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'xterm'):
        binary = shutil.which(name)
        if binary:
            separator = '--' if name == 'gnome-terminal' else '-x' if name == 'xfce4-terminal' else '-e'
            return [binary, separator, *command]
    raise RuntimeError('Не найден терминал. Установите xterm или другой эмулятор терминала.')


class ServerStore:
    def __init__(self, config):
        self.config = Path(config)
        self.servers = []
        self.error = ''
        self.read_only = False
        try:
            data = json.loads(self.config.read_text())
            if isinstance(data, dict) and 'host' in data:
                profile = credentials(data['host'], data['user'], data['port'])
                self.servers = [dict(profile, id=str(uuid.uuid4()), name=profile['host'],
                                     description='', secret_key=identity(profile), has_password=True)]
                self.write(self.servers)
            else:
                if data.get('version') != 2 or not isinstance(data.get('servers'), list):
                    raise ValueError('Неизвестный формат списка серверов')
                seen = set()
                for item in data['servers']:
                    profile = credentials(item['host'], item['user'], item['port'])
                    if not isinstance(item['id'], str) or item['id'] in seen:
                        raise ValueError('Некорректный идентификатор сервера')
                    seen.add(item['id'])
                    self.servers.append(dict(profile, id=item['id'], name=str(item['name']),
                        description=str(item.get('description', '')), secret_key=str(item['secret_key']),
                        has_password=bool(item.get('has_password', False))))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.servers = []
            self.read_only = True
            self.error = 'Не удалось прочитать список серверов. Файл не изменён.\n' + str(exc)

    def write(self, servers):
        if self.read_only:
            raise RuntimeError(self.error)
        self.config.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 2, 'servers': servers}, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(self.config)

    def save(self, server_id, name, description, profile, password=''):
        if self.read_only:
            raise RuntimeError(self.error)
        profile = credentials(profile['host'], profile['user'], profile['port'])
        name = name.strip()
        if not name:
            raise ValueError('Введите название сервера.')
        existing = next((item for item in self.servers if item['id'] == server_id), None)
        server_id = existing['id'] if existing else str(uuid.uuid4())
        item = dict(profile, id=server_id, name=name, description=description.strip(),
                    secret_key=existing['secret_key'] if existing else 'server:' + server_id,
                    has_password=existing.get('has_password', False) if existing else False)
        if password:
            try:
                vault().set_password(SERVICE, item['secret_key'], password)
            except Exception as exc:
                raise RuntimeError('Не удалось сохранить пароль в системном хранилище.\nРазблокируйте системное хранилище ключей (Keychain на macOS или Secret Service на Linux).') from exc
            item['has_password'] = True
        updated = [item if old['id'] == server_id else old for old in self.servers]
        if not existing:
            updated.append(item)
        self.write(updated)
        self.servers = updated
        return item

    def delete_password(self, server_id):
        if self.read_only:
            raise RuntimeError(self.error)
        item = next(s for s in self.servers if s['id'] == server_id)
        if item.get('has_password'):
            backend = vault()
            if backend.get_password(SERVICE, item['secret_key']) is not None:
                backend.delete_password(SERVICE, item['secret_key'])
        updated = [dict(s, has_password=False) if s['id'] == server_id else s for s in self.servers]
        self.write(updated)
        self.servers = updated

    def delete(self, server_id):
        self.delete_password(server_id)
        updated = [s for s in self.servers if s['id'] != server_id]
        self.write(updated)
        self.servers = updated


def helper_invocation():
    if getattr(sys, 'frozen', False):
        helper = Path(sys.executable).resolve().parent.parent / 'Helpers' / 'node-desk-helper' / 'node-desk-helper'
        if not helper.is_file():
            raise RuntimeError('Не найден SSH helper внутри приложения. Переустановите Node Desk.')
        return str(helper), [str(helper)]
    source = Path(__file__).resolve().with_name('ssh_helper.py')
    # OpenSSH accepts a single executable for SSH_ASKPASS, with no interpreter args.
    # This wrapper contains only program paths, never credentials or passwords.
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    wrapper = directory / 'ssh-askpass'
    temporary = directory / 'ssh-askpass.tmp'
    temporary.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(source)]) + ' "$@"\n')
    temporary.chmod(0o700)
    temporary.replace(wrapper)
    return str(wrapper), [sys.executable, str(source)]


def mac_terminal_command(command, connection_env):
    public_env = ['env'] + [f'{key}={value}' for key, value in connection_env.items()]
    script = ('on run argv\n'
              'tell application "Terminal"\n'
              'activate\n'
              'do script (item 1 of argv)\n'
              'end tell\n'
              'end run')
    return ['/usr/bin/osascript', '-e', script, shlex.join(public_env + command)]


def launch_server(server):
    if not shutil.which('ssh') and not Path('/usr/bin/ssh').is_file():
        raise RuntimeError('Не найден OpenSSH client.')
    profile = credentials(server['host'], server['user'], server['port'])
    askpass_path, helper_command = helper_invocation()
    connection_env = {
        'SSH_ASKPASS': askpass_path,
        'SSH_ASKPASS_REQUIRE': 'force',
        'TAILSCALE_UI_SSH_PROFILE': identity(profile),
        'TAILSCALE_UI_SSH_SECRET_KEY': server['secret_key'],
    }
    command = helper_command + ['--session', identity(profile)]
    if sys.platform == 'darwin':
        # Terminal has its own environment; pass only these public connection values.
        result = subprocess.run(mac_terminal_command(command, connection_env), capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('Не удалось открыть Terminal. Разрешите управление Terminal в настройках macOS.\n' + result.stderr.strip())
    else:
        subprocess.Popen(terminal_command(command), env={**os.environ, **connection_env}, start_new_session=True)


class SSHFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=24)
        config = config_dir() / 'ssh.json'
        self.store = ServerStore(config)
        self.current_id = None
        self.show_list()
        if self.store.error:
            self.after_idle(lambda: messagebox.showerror('Список серверов', self.store.error, parent=self))

    def clear(self):
        self.editor_open = False
        for child in self.winfo_children():
            child.destroy()

    def show_list(self):
        self.clear()
        self.current_id = None
        heading = ttk.Frame(self)
        heading.pack(fill='x', pady=(0, 6))
        ttk.Label(heading, text='Серверы', font=('Sans', 24, 'bold')).pack(side='left')
        ttk.Button(heading, text='+ Добавить сервер', style='Action.TButton', command=lambda: self.edit()).pack(side='right')
        self.count = ttk.Label(self, text=f'Всего: {len(self.store.servers)}', style='Muted.TLabel')
        self.count.pack(anchor='w', pady=(0, 20))
        self.search = tk.StringVar()
        search = ttk.Entry(self, textvariable=self.search, font=('Sans', 11))
        search.pack(fill='x', pady=(0, 16))
        # Search matches the name, description, IP and username.
        ttk.Label(self, text='Поиск по названию, IP или описанию', style='Muted.TLabel').pack(anchor='w', before=search, pady=(0, 8))
        self.search.trace_add('write', lambda *_: self.render_rows())
        area = ttk.Frame(self)
        area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, bg='#0d111b', highlightthickness=0)
        bar = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.rows = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.rows, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.rows.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.note = ttk.Label(self, text='', style='Muted.TLabel')
        self.note.pack(anchor='w', pady=(12, 0))
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        if sys.platform != 'darwin':
            self.canvas.bind('<Button-4>', lambda e: self.canvas.yview_scroll(-2, 'units'))
            self.canvas.bind('<Button-5>', lambda e: self.canvas.yview_scroll(2, 'units'))
        self.render_rows()

    def render_rows(self):
        for child in self.rows.winfo_children():
            child.destroy()
        query = self.search.get().strip().casefold()
        servers = [s for s in self.store.servers if query in ' '.join(
            str(s[k]) for k in ('name', 'description', 'host', 'user', 'port')).casefold()]
        self.count.configure(text=f'{len(servers)} / {len(self.store.servers)} серверов' if query else f'{len(servers)} серверов')
        if not servers:
            ttk.Label(self.rows, text='Ничего не найдено' if query else 'Добавьте первый сервер', style='Muted.TLabel').pack(pady=64)
        for server in servers:
            card = ttk.Frame(self.rows, style='Card.TFrame', padding=18)
            card.pack(fill='x', pady=(0, 10))
            connect = ttk.Button(card, text='Подключиться', style='SmallAction.TButton', command=lambda s=server: self.connect(s))
            connect.pack(side='right', padx=(16, 0))
            info = ttk.Frame(card, style='Card.TFrame', cursor='hand2')
            info.pack(side='left', fill='both', expand=True)
            name = ttk.Label(info, text=server['name'], style='Card.TLabel', font=('Sans', 13, 'bold'), cursor='hand2')
            name.pack(anchor='w')
            address = ttk.Label(info, text=f"{server['user']}@{server['host']} : {server['port']}", style='CardMuted.TLabel', font=('Sans', 10), cursor='hand2')
            address.pack(anchor='w', pady=(5, 0))
            widgets = [card, info, name, address]
            if server['description']:
                summary = ' '.join(server['description'].split())
                summary = summary[:137] + '…' if len(summary) > 140 else summary
                description = ttk.Label(info, text=summary, style='CardMuted.TLabel', wraplength=390, cursor='hand2')
                description.pack(anchor='w', pady=(8, 0))
                widgets.append(description)
            for widget in widgets:
                widget.bind('<Button-1>', lambda event, s=server: self.edit(s))
            info.bind('<Return>', lambda event, s=server: self.edit(s))
            ttk.Button(info, text='Открыть →', style='Link.TButton', command=lambda s=server: self.edit(s)).pack(anchor='w', pady=(8, 0))
        def bind_scroll(widget):
            widget.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
            if sys.platform != 'darwin':
                widget.bind('<Button-4>', lambda e: self.canvas.yview_scroll(-2, 'units'))
                widget.bind('<Button-5>', lambda e: self.canvas.yview_scroll(2, 'units'))
            for child in widget.winfo_children():
                bind_scroll(child)
        bind_scroll(self.rows)

    def connect(self, server):
        try:
            launch_server(server)
            self.note.configure(text='Терминал открыт: ' + server['name'])
        except Exception as exc:
            messagebox.showerror('Ошибка SSH', str(exc), parent=self)

    def edit(self, server=None):
        self.clear()
        self.editor_open = True
        self.current_id = server['id'] if server else None
        values = server or {}
        header = ttk.Frame(self)
        header.pack(fill='x', pady=(0, 20))
        ttk.Button(header, text='← Серверы', style='Save.TButton', command=self.back).pack(side='left')
        ttk.Label(header, text='Настройки сервера' if server else 'Новый сервер', font=('Sans', 18, 'bold')).pack(side='left', padx=16)
        card = ttk.Frame(self, style='Card.TFrame', padding=24)
        card.pack(fill='both', expand=True)
        self.fields = {}
        for key, title, default in [('name', 'Название', ''), ('host', 'IP сервера', ''), ('port', 'Порт', '22'), ('user', 'Пользователь', '')]:
            row = ttk.Frame(card, style='Card.TFrame')
            row.pack(fill='x', pady=(0, 12))
            ttk.Label(row, text=title, style='CardMuted.TLabel', width=16).pack(side='left')
            variable = tk.StringVar(value=str(values.get(key, default)))
            ttk.Entry(row, textvariable=variable, font=('Sans', 11)).pack(side='right', fill='x', expand=True)
            self.fields[key] = variable
        row = ttk.Frame(card, style='Card.TFrame')
        row.pack(fill='x', pady=(0, 12))
        ttk.Label(row, text='Пароль', style='CardMuted.TLabel', width=16).pack(side='left')
        self.password = tk.StringVar()
        ttk.Entry(row, textvariable=self.password, show='●', font=('Sans', 11)).pack(side='right', fill='x', expand=True)
        password_row = ttk.Frame(card, style='Card.TFrame')
        password_row.pack(fill='x', pady=(0, 16))
        stored = bool(values.get('has_password'))
        self.password_state = ttk.Label(password_row, text='Пароль сохранён' if stored else 'Пароль не сохранён', style='CardMuted.TLabel', font=('Sans', 9))
        self.password_state.pack(side='left')
        if stored:
            self.remove_password = ttk.Button(password_row, text='Удалить пароль', style='Link.TButton', command=self.delete_password)
            self.remove_password.pack(side='right')
        ttk.Label(card, text='Описание', style='CardMuted.TLabel').pack(anchor='w', pady=(0, 8))
        self.description = tk.Text(card, height=3, bg='#0d111b', fg='#e6edf7', insertbackground='#e6edf7',
                                   relief='flat', font=('Sans', 11), padx=12, pady=10, wrap='word', highlightthickness=1,
                                   highlightbackground='#293247', highlightcolor='#668aff')
        self.description.pack(fill='both', expand=True, pady=(0, 20))
        self.description.insert('1.0', values.get('description', ''))
        actions = ttk.Frame(card, style='Card.TFrame')
        actions.pack(fill='x')
        ttk.Button(actions, text='Сохранить', style='Action.TButton', command=self.save).pack(side='right')
        if server:
            ttk.Button(actions, text='Удалить сервер', style='Danger.TButton', command=self.delete).pack(side='left')
        self.initial = self.form_values()

    def form_values(self):
        return tuple(self.fields[k].get() for k in ('name', 'host', 'port', 'user')) + (self.description.get('1.0', 'end-1c'), self.password.get())

    def confirm_close(self):
        if self.editor_open and self.form_values() != self.initial:
            return messagebox.askyesno('Несохранённые изменения', 'Закрыть карточку без сохранения?', parent=self)
        return True

    def back(self):
        if self.confirm_close():
            self.show_list()

    def save(self):
        try:
            profile = credentials(*(self.fields[k].get() for k in ('host', 'user', 'port')))
            self.store.save(self.current_id, self.fields['name'].get(), self.description.get('1.0', 'end-1c'), profile, self.password.get())
            self.password.set('')
            self.show_list()
            self.note.configure(text='Сервер сохранён')
        except Exception as exc:
            messagebox.showerror('Ошибка сохранения', str(exc), parent=self)

    def delete_password(self):
        try:
            self.store.delete_password(self.current_id)
            self.password.set('')
            self.password_state.configure(text='Пароль не сохранён')
            self.remove_password.configure(state='disabled')
            # Preserve any other edits in the form.
            self.initial = self.initial[:-1] + ('',)
            messagebox.showinfo('SSH', 'Сохранённый пароль удалён.', parent=self)
        except Exception as exc:
            messagebox.showerror('Ошибка удаления пароля', str(exc), parent=self)

    def delete(self):
        if not messagebox.askyesno('Удалить сервер', 'Удалить сервер и его сохранённый пароль?', parent=self):
            return
        try:
            self.store.delete(self.current_id)
            self.show_list()
        except Exception as exc:
            messagebox.showerror('Ошибка удаления', str(exc), parent=self)


def askpass(prompt):
    profile = json.loads(os.environ['TAILSCALE_UI_SSH_PROFILE'])
    # SSH explicitly marks host-key confirmation prompts.
    if os.environ.get('SSH_ASKPASS_PROMPT') == 'confirm' or 'yes/no' in prompt:
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesno('Проверка ключа SSH-сервера', prompt, parent=root)
        root.destroy()
        print('yes' if answer else 'no')
        return 0
    if 'password:' in prompt.lower():
        try:
            password = vault().get_password(SERVICE, os.environ.get('TAILSCALE_UI_SSH_SECRET_KEY') or identity(profile))
        except Exception:
            password = None
        if password is not None:
            print(password)
            return 0
    root = tk.Tk()
    root.withdraw()
    answer = simpledialog.askstring('SSH', prompt, show='●', parent=root)
    root.destroy()
    if answer is None:
        return 1
    print(answer)
    return 0


def run_session(profile):
    result = subprocess.run(ssh_command(profile))
    if result.returncode:
        print('\nSSH завершился с ошибкой. Код:', result.returncode)
        try:
            input('Нажмите Enter, чтобы закрыть окно…')
        except EOFError:
            pass
    return result.returncode


if __name__ == '__main__':
    from ssh_helper import main
    sys.exit(main())
