"""Consistent dark ttk controls, including readonly and disabled states."""
import os
import tkinter as tk
from tkinter import ttk, scrolledtext

COLORS = {
    'bg': '#111827', 'panel': '#182235', 'field': '#202e43',
    'text': '#f1f5f9', 'muted': '#b6c3d5', 'border': '#40536e',
    'button': '#293c56', 'hover': '#365170', 'pressed': '#21334a',
    'accent': '#5ee0bd', 'accent_hover': '#8aeccc', 'ink': '#10271f',
    'selected': '#325979', 'disabled': '#1c293b', 'disabled_text': '#9aaac1',
    'error': '#ffb4b4',
}


def apply_theme(root):
    c = COLORS
    root.configure(bg=c['bg'])
    # The dropdown's Listbox is a classic Tk widget, not a ttk Combobox field.
    for option, value in {'background': c['field'], 'foreground': c['text'],
                          'selectBackground': c['selected'], 'selectForeground': c['text'],
                          'highlightThickness': 0, 'borderWidth': 0,
                          'font': '{Segoe UI} 10'}.items():
        root.option_add('*TCombobox*Listbox.' + option, value)
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=c['bg'], foreground=c['text'],
                 fieldbackground=c['field'], bordercolor=c['border'],
                 lightcolor=c['border'], darkcolor=c['border'],
                 selectbackground=c['selected'], selectforeground=c['text'],
                 font=('Segoe UI', 10))
    st.configure('TFrame', background=c['bg'])
    st.configure('TLabel', background=c['bg'], foreground=c['text'])
    st.configure('Hero.TLabel', font=('Segoe UI', 20, 'bold'))
    st.configure('TButton', padding=(11, 7), background=c['button'],
                 foreground=c['text'], borderwidth=1, focuscolor=c['accent'])
    st.map('TButton', background=[('disabled', c['disabled']), ('pressed', c['pressed']),
                                 ('active', c['hover'])],
           foreground=[('disabled', c['disabled_text']), ('!disabled', c['text'])],
           bordercolor=[('focus', c['accent']), ('!focus', c['border'])])
    st.configure('Go.TButton', background=c['accent'], foreground=c['ink'],
                 font=('Segoe UI', 10, 'bold'))
    st.map('Go.TButton', background=[('disabled', c['disabled']), ('pressed', '#46b99b'),
                                    ('active', c['accent_hover']), ('!disabled', c['accent'])],
           foreground=[('disabled', c['disabled_text']), ('!disabled', c['ink'])])
    st.configure('TNotebook', background=c['bg'], borderwidth=0, tabmargins=(0, 0, 0, 5))
    st.configure('TNotebook.Tab', padding=(16, 9), background=c['panel'],
                 foreground=c['muted'], borderwidth=0)
    st.map('TNotebook.Tab', background=[('selected', c['selected']), ('active', c['hover']),
                                       ('!selected', c['panel'])],
           foreground=[('selected', c['text']), ('active', c['text']), ('!selected', c['muted'])],
           padding=[('selected', (16, 9)), ('!selected', (16, 9))],
           lightcolor=[('selected', c['accent'])])
    for name in ('TEntry', 'TCombobox'):
        st.configure(name, padding=5, fieldbackground=c['field'], foreground=c['text'],
                     insertcolor=c['text'], background=c['button'], arrowcolor=c['text'])
        st.map(name, fieldbackground=[('disabled', c['disabled']), ('readonly', c['field']),
                                     ('!disabled', c['field'])],
               background=[('disabled', c['disabled']), ('pressed', c['pressed']),
                           ('active', c['hover']), ('!disabled', c['button'])],
               foreground=[('disabled', c['disabled_text']), ('readonly', c['text'])],
               selectbackground=[('!disabled', c['selected'])],
               selectforeground=[('!disabled', c['text'])],
               bordercolor=[('focus', c['accent']), ('!focus', c['border'])],
               lightcolor=[('focus', c['accent']), ('!focus', c['border'])],
               darkcolor=[('focus', c['accent']), ('!focus', c['border'])],
               arrowcolor=[('disabled', c['disabled_text']), ('!disabled', c['text'])])
    st.configure('ComboboxPopdownFrame', background=c['field'], bordercolor=c['border'])
    st.configure('TCheckbutton', indicatorbackground=c['field'],
                 indicatorforeground=c['ink'], indicatormargin=5, focuscolor=c['accent'])
    st.map('TCheckbutton', background=[('active', c['bg'])],
           foreground=[('disabled', c['disabled_text']), ('!disabled', c['text'])],
           indicatorbackground=[('selected', c['accent']), ('!selected', c['field'])])
    for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        st.configure(name, background=c['border'], troughcolor=c['panel'],
                     arrowcolor=c['text'], bordercolor=c['panel'],
                     lightcolor=c['border'], darkcolor=c['border'], arrowsize=14)
        st.map(name, background=[('active', c['hover']), ('pressed', c['selected'])])
    st.configure('TSeparator', background=c['border'])
    root.after_idle(lambda: dark_titlebar(root))
    return st


def dark_titlebar(window):
    """Optional native Windows 11 title-bar color; other platforms need no API."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        from ctypes import wintypes
        parent = ctypes.windll.user32.GetParent
        parent.argtypes = [wintypes.HWND]; parent.restype = wintypes.HWND
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        enabled = ctypes.c_int(1)
        set_attribute(parent(window.winfo_id()), 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except (AttributeError, OSError, tk.TclError):
        pass


def text_box(parent, height=5):
    c = COLORS
    box = scrolledtext.ScrolledText(parent, height=height, wrap='word',
        bg=c['field'], fg=c['text'], insertbackground=c['text'],
        selectbackground=c['selected'], selectforeground=c['text'],
        font=('Segoe UI', 10), relief='flat', borderwidth=0,
        highlightthickness=1, highlightbackground=c['border'], highlightcolor=c['accent'],
        padx=8, pady=7)
    box.frame.configure(bg=c['bg'])
    box.vbar.destroy()
    box.vbar = ttk.Scrollbar(box.frame, orient='vertical', command=box.yview)
    box.vbar.pack(side='right', fill='y')
    box.configure(yscrollcommand=box.vbar.set)
    return box


def dialog(parent, title, message, question=False, error=False):
    """Small modal app dialog. File pickers still use the native Windows UI."""
    c = COLORS
    win = tk.Toplevel(parent)
    win.withdraw(); win.title(title); win.configure(bg=c['bg'])
    win.transient(parent); win.resizable(False, False)
    result = [False]
    body = ttk.Frame(win, padding=22); body.pack(fill='both', expand=True)
    ttk.Label(body, text=title, font=('Segoe UI', 13, 'bold'),
              foreground=c['error'] if error else c['text']).pack(anchor='w', pady=(0, 10))
    ttk.Label(body, text=message, wraplength=480, justify='left').pack(anchor='w')
    buttons = ttk.Frame(body); buttons.pack(fill='x', pady=(20, 0))
    def finish(value=False):
        result[0] = value
        win.destroy()
    if error:
        def copy():
            parent.clipboard_clear(); parent.clipboard_append(message)
        ttk.Button(buttons, text='Copy error', command=copy).pack(side='left')
    if question:
        ttk.Button(buttons, text='Yes', command=lambda: finish(True), style='Go.TButton').pack(side='right', padx=(8, 0))
    default = ttk.Button(buttons, text='Cancel' if question else 'OK', command=finish)
    default.pack(side='right')
    win.bind('<Escape>', lambda event: finish())
    def enter(event):
        focused = win.focus_get()
        if isinstance(focused, ttk.Button): focused.invoke()
        else: default.invoke()
        return 'break'
    win.bind('<Return>', enter)
    win.protocol('WM_DELETE_WINDOW', finish)
    win.update_idletasks()
    x = max(0, min(parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2,
                   win.winfo_screenwidth() - win.winfo_reqwidth()))
    y = max(0, min(parent.winfo_rooty() + (parent.winfo_height() - win.winfo_reqheight()) // 2,
                   win.winfo_screenheight() - win.winfo_reqheight() - 60))
    win.geometry(f'+{x}+{y}'); win.deiconify(); dark_titlebar(win)
    win.wait_visibility(); win.grab_set(); default.focus_set(); parent.wait_window(win)
    return result[0]
