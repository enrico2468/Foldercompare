#!/usr/bin/env python3
"""
Folder Sync GUI
A simple desktop app to sync media files between folders.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import datetime as _dt
import json
import shutil
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Dict, Set, Tuple, List, Optional

CONFIG_PATH = Path.home() / ".config" / "foldercompare" / "state.json"

def find_dupes_tool() -> Optional[str]:
    """Return path to fdupes or jdupes (drop-in compatible), or None."""
    return shutil.which('fdupes') or shutil.which('jdupes')

DUPES_TOOL = find_dupes_tool()

def format_size(num_bytes: int) -> str:
    """Human-readable byte count (e.g. '4.2 GB')."""
    size = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"

def load_state() -> Dict[str, str]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

def save_state(state: Dict[str, str]) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(state, indent=2))
    except OSError:
        pass

# ============================================================================
# SYNC LOGIC (extracted from compare_folders.py)
# ============================================================================

IMAGE_EXTS = {
    # Common
    '.jpg', '.jpeg', '.jfif', '.png', '.gif', '.bmp', '.webp', '.avif',
    # High-quality / scans / iPhone
    '.tiff', '.tif', '.heic', '.heif',
    # Vector and editor formats
    '.svg', '.psd', '.xcf',
    # Camera RAW
    '.raw', '.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.raf', '.rw2', '.pef',
}
VIDEO_EXTS = {
    '.mp4', '.m4v', '.mov', '.avi', '.mkv', '.webm', '.wmv',
    '.mpg', '.mpeg', '.3gp', '.flv', '.ogv', '.vob',
    '.ts', '.mts', '.m2ts',
}
AUDIO_EXTS = {
    '.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.opus', '.wma', '.aiff',
}
DOCUMENT_EXTS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.odt', '.ods', '.odp', '.txt', '.rtf', '.md', '.csv',
}

def get_media_type(filename: str) -> str:
    """Return 'image', 'video', 'audio', 'document', or 'other'"""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return 'image'
    elif ext in VIDEO_EXTS:
        return 'video'
    elif ext in AUDIO_EXTS:
        return 'audio'
    elif ext in DOCUMENT_EXTS:
        return 'document'
    return 'other'

def is_media_file(filepath: str) -> bool:
    """Check if file is a supported media type"""
    return get_media_type(filepath) != 'other'

def detect_naming_pattern(folder: str) -> Tuple[Optional[str], int]:
    """
    Detect naming pattern from existing files.
    Returns (prefix, next_number) or (None, 1) if no pattern found.
    """
    pattern = re.compile(r'^(.+?)\s*(\d+)\.(\w+)$')
    max_image = 0
    max_video = 0
    found_prefix = None

    for entry in os.scandir(folder):
        if entry.is_file() and is_media_file(entry.name):
            match = pattern.match(entry.name)
            if match:
                prefix = match.group(1).strip()
                num = int(match.group(2))
                ext = Path(entry.name).suffix.lower()
                media_type = get_media_type(entry.name)

                if found_prefix is None:
                    found_prefix = prefix

                if media_type == 'image':
                    max_image = max(max_image, num)
                elif media_type == 'video':
                    max_video = max(max_video, num)

    return found_prefix, max(max_image, max_video) + 1

def collect_source_files(source: str, include_all: bool = False) -> Tuple[Dict[str, List[Tuple[str, str]]], int, Dict[str, int]]:
    """
    Collect files from source, grouped by relative folder path.
    Returns: (grouped, skipped_count, skipped_by_ext)
    When include_all is True, every file is included; skipped_count is 0.
    Otherwise, only files in IMAGE/VIDEO/AUDIO_EXTS are included; the rest
    are counted and tallied per-extension for the preview header.
    """
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    skipped = 0
    skipped_by_ext: Dict[str, int] = {}

    for root, dirs, files in os.walk(source):
        for filename in sorted(files):
            included = include_all or is_media_file(filename)
            if not included:
                skipped += 1
                ext = Path(filename).suffix.lower() or '(no extension)'
                skipped_by_ext[ext] = skipped_by_ext.get(ext, 0) + 1
                continue

            full_path = os.path.join(root, filename)
            rel_folder = os.path.relpath(root, source)
            if rel_folder == '.':
                rel_folder = ''
            grouped.setdefault(rel_folder, []).append((filename, full_path))

    return grouped, skipped, skipped_by_ext

DEFAULT_RENUMBER = {
    'image': True,
    'video': True,
    'audio': True,
    'document': False,
}

def _should_rename(filename: str, renumber: Dict[str, bool]) -> bool:
    """Decide whether a file gets the destination's numbered name or keeps its original."""
    return renumber.get(get_media_type(filename), False)

def _resolve_collision(dest_path: str, strategy: str, taken: Set[str]) -> Optional[str]:
    """
    Resolve a filename collision on disk or within the planned batch.
    Returns the path to use, or None if the file should be skipped.
    """
    if not (os.path.exists(dest_path) or dest_path in taken):
        return dest_path
    if strategy == 'skip':
        return None
    if strategy == 'overwrite':
        return dest_path

    p = Path(dest_path)
    parent, stem, ext = str(p.parent), p.stem, p.suffix

    if strategy == 'date':
        today = _dt.date.today().isoformat()
        candidate = os.path.join(parent, f"{stem} {today}{ext}")
        if not (os.path.exists(candidate) or candidate in taken):
            return candidate
        n = 2
        while True:
            candidate = os.path.join(parent, f"{stem} {today} ({n}){ext}")
            if not (os.path.exists(candidate) or candidate in taken):
                return candidate
            n += 1

    # 'version' strategy (also used as fallback for unknown strategies)
    n = 2
    while True:
        candidate = os.path.join(parent, f"{stem} ({n}){ext}")
        if not (os.path.exists(candidate) or candidate in taken):
            return candidate
        n += 1

def plan_sync(source: str, destination: str,
              include_all: bool = False,
              renumber: Optional[Dict[str, bool]] = None,
              collision: str = 'version'
              ) -> Tuple[List[Tuple[str, str, str]], Dict[str, int], int, Dict[str, int], int]:
    """
    Plan the sync operation.
    Returns: (plan, counters, skipped_count, skipped_by_ext, conflicts)
    """
    if renumber is None:
        renumber = DEFAULT_RENUMBER
    plan = []
    counters: Dict[str, int] = {}  # folder -> next number
    taken: Set[str] = set()
    conflicts = 0

    grouped, skipped, skipped_by_ext = collect_source_files(source, include_all=include_all)

    for rel_folder, files in grouped.items():
        dest_folder = os.path.join(destination, rel_folder) if rel_folder else destination

        # Ensure dest folder exists in counters
        if dest_folder not in counters:
            prefix, start_num = detect_naming_pattern(dest_folder)
            counters[dest_folder] = start_num

        for filename, full_path in files:
            ext = Path(filename).suffix.lower()

            if not _should_rename(filename, renumber):
                # Keep original filename (any type whose renumber toggle is off, or 'other' files)
                dest_file = os.path.join(dest_folder, filename)
                if os.path.exists(dest_file) or dest_file in taken:
                    conflicts += 1
                    resolved = _resolve_collision(dest_file, collision, taken)
                    if resolved is None:
                        continue  # skip strategy
                    dest_file = resolved
                taken.add(dest_file)
                plan.append((full_path, dest_file, dest_folder))
                continue

            # Get or create prefix
            if counters[dest_folder] == 1:
                prefix, _ = detect_naming_pattern(dest_folder)
                if prefix is None:
                    base = Path(filename).stem
                    prefix = re.sub(r'\s*\d+\s*$', '', base)
            else:
                existing_files = list(Path(dest_folder).glob('*'))
                if existing_files:
                    prefix, _ = detect_naming_pattern(dest_folder)
                    if prefix is None:
                        prefix = Path(filename).stem

            new_name = f"{prefix} {counters[dest_folder]}{ext}"
            dest_file = os.path.join(dest_folder, new_name)

            taken.add(dest_file)
            plan.append((full_path, dest_file, dest_folder))
            counters[dest_folder] += 1

    return plan, counters, skipped, skipped_by_ext, conflicts

def execute_sync(plan: List[Tuple[str, str, str]],
                 progress_callback=None,
                 status_callback=None) -> Tuple[int, int, List[str], List[str]]:
    """
    Execute the sync plan.
    Returns: (success_count, error_count, error_messages, copied_source_paths)
    """
    success = 0
    errors = 0
    error_msgs = []
    copied_sources: List[str] = []

    # Create all destination folders first
    dest_folders = set(item[2] for item in plan)
    for folder in dest_folders:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                error_msgs.append(f"Failed to create folder {folder}: {e}")
                errors += 1

    # Copy files
    total = len(plan)
    for i, (src, dest, _) in enumerate(plan):
        if progress_callback:
            progress_callback(i + 1, total)

        try:
            shutil.copy2(src, dest)
            success += 1
            copied_sources.append(src)
            if status_callback:
                status_callback(f"Copied: {Path(src).name} → {Path(dest).name}")
        except Exception as e:
            errors += 1
            msg = f"Error copying {Path(src).name}: {e}"
            error_msgs.append(msg)
            if status_callback:
                status_callback(f"❌ {msg}")

    return success, errors, error_msgs, copied_sources

def find_cross_duplicates(source: str, destination: str) -> List[Dict[str, List[str]]]:
    """
    Run fdupes (or jdupes) between source and destination, return groups
    that span both. Each group is {'source': [paths in source], 'dest': [paths in dest]}.
    """
    tool = find_dupes_tool()
    if tool is None:
        raise FileNotFoundError(
            "Neither 'fdupes' nor 'jdupes' was found on PATH. "
            "Install one of them to enable duplicate checking."
        )

    src = os.path.abspath(source)
    dest = os.path.abspath(destination)
    src_prefix = src.rstrip(os.sep) + os.sep
    dest_prefix = dest.rstrip(os.sep) + os.sep

    result = subprocess.run(
        [tool, '-r', src, dest],
        capture_output=True, text=True, check=False
    )
    # fdupes/jdupes exit non-zero on certain conditions but still produce useful output
    if result.returncode not in (0, 1) and not result.stdout:
        raise RuntimeError(f"{Path(tool).name} failed: {result.stderr.strip()}")

    groups: List[List[str]] = []
    current: List[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                groups.append(current)
                current = []
        else:
            current.append(line)
    if current:
        groups.append(current)

    cross = []
    for group in groups:
        src_files = [f for f in group if os.path.abspath(f).startswith(src_prefix)]
        dest_files = [f for f in group if os.path.abspath(f).startswith(dest_prefix)]
        if src_files and dest_files:
            cross.append({'source': src_files, 'dest': dest_files})
    return cross

# ============================================================================
# GUI APPLICATION
# ============================================================================

PALETTE = {
    'bg':         '#eef3f8',  # very light blue-grey window background
    'panel':      '#fff3a8',  # butter-yellow console panel for inputs / preview
    'text':       '#1f2d3d',  # near-black with a hint of blue
    'accent':     '#2e7dc1',  # primary blue accent
    'accent_hi':  '#225e92',  # darker blue for button hover/active
    'accent_lo':  '#9bbfde',  # lighter blue for disabled buttons
    'danger':     '#c0392b',  # red for destructive actions
    'danger_hi':  '#962d22',  # darker red for hover
    'danger_lo':  '#e0a8a2',  # muted red for disabled
    'neutral':    '#5d6b7c',  # slate grey for Close
    'neutral_hi': '#3f4a58',
    'border':     '#cdd6e0',
}

def _apply_theme(root: tk.Tk) -> None:
    """Switch ttk to 'clam' and apply a soft blue palette."""
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    p = PALETTE
    root.configure(bg=p['bg'])

    style.configure('.', background=p['bg'], foreground=p['text'], font=('Segoe UI', 10))
    style.configure('TFrame', background=p['bg'])
    style.configure('TLabel', background=p['bg'], foreground=p['text'])
    style.configure('TLabelframe', background=p['bg'], foreground=p['text'],
                    bordercolor=p['border'], relief='groove')
    style.configure('TLabelframe.Label', background=p['bg'], foreground=p['accent'],
                    font=('Segoe UI', 10, 'bold'))
    style.configure('TCheckbutton', background=p['bg'], foreground=p['text'])
    style.map('TCheckbutton', background=[('active', p['bg'])])
    style.configure('TEntry', fieldbackground=p['panel'], foreground=p['text'],
                    bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'])
    style.configure('TButton', background=p['accent'], foreground='white',
                    bordercolor=p['accent'], focuscolor=p['accent'],
                    padding=(12, 6), font=('Segoe UI', 10))
    style.map('TButton',
              background=[('active', p['accent_hi']), ('disabled', p['accent_lo'])],
              foreground=[('disabled', '#f0f4f8')])
    style.configure('Danger.TButton', background=p['danger'], foreground='white',
                    bordercolor=p['danger'], focuscolor=p['danger'],
                    padding=(12, 6), font=('Segoe UI', 10, 'bold'))
    style.map('Danger.TButton',
              background=[('active', p['danger_hi']), ('disabled', p['danger_lo'])],
              foreground=[('disabled', '#f8e8e6')])
    style.configure('Neutral.TButton', background=p['neutral'], foreground='white',
                    bordercolor=p['neutral'], focuscolor=p['neutral'],
                    padding=(12, 6), font=('Segoe UI', 10))
    style.map('Neutral.TButton',
              background=[('active', p['neutral_hi'])])
    style.configure('Title.TLabel', background=p['bg'], foreground=p['accent'],
                    font=('Segoe UI', 22, 'bold'))
    style.configure('Subtitle.TLabel', background=p['bg'], foreground=p['text'],
                    font=('Segoe UI', 10))
    style.configure('Horizontal.TProgressbar',
                    background=p['accent'], troughcolor=p['border'],
                    bordercolor=p['border'], lightcolor=p['accent'], darkcolor=p['accent'])

class FolderSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Folder Sync")
        self.root.geometry("920x960")
        self.root.minsize(880, 880)
        self.root.resizable(True, True)
        _apply_theme(self.root)

        # Variables
        self.source_path = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.include_all = tk.BooleanVar(value=False)
        self.renumber_vars = {
            'image': tk.BooleanVar(value=True),
            'video': tk.BooleanVar(value=True),
            'audio': tk.BooleanVar(value=True),
            'document': tk.BooleanVar(value=False),
        }
        # Filename-collision strategy: (label shown in dropdown, internal key)
        self._collision_options = [
            ("Add version suffix — file (2).ext", 'version'),
            ("Add date suffix — file 2026-05-03.ext", 'date'),
            ("Skip — keep destination", 'skip'),
            ("Overwrite destination", 'overwrite'),
        ]
        self.collision_label = tk.StringVar(value=self._collision_options[0][0])
        self.plan: List[Tuple[str, str, str]] = []
        self.duplicate_groups: List[Dict[str, List[str]]] = []

        # Restore last-used folders if they still exist
        state = load_state()
        last_src = state.get('source', '')
        last_dest = state.get('destination', '')
        if last_src and os.path.isdir(last_src):
            self.source_path.set(last_src)
        if last_dest and os.path.isdir(last_dest):
            self.dest_path.set(last_dest)

        self._build_ui()

        # Disable duplicate check if no tool is installed
        if DUPES_TOOL is None:
            self.check_dupes_btn.config(state=tk.DISABLED)
            self._set_status(
                "Note: install 'fdupes' (or 'jdupes') to enable duplicate checking. Sync still works."
            )

    def _build_ui(self):
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(main_frame, text="Folder Sync", style='Title.TLabel')
        title_label.pack(pady=(0, 5))

        # Description
        desc_label = ttk.Label(
            main_frame,
            text="Sync media files from source to destination with automatic naming.",
            style='Subtitle.TLabel'
        )
        desc_label.pack(pady=(0, 20))

        # Folder selection frame
        folder_frame = ttk.LabelFrame(main_frame, text="Folders", padding="10")
        folder_frame.pack(fill=tk.X, pady=(0, 15))

        # Source folder
        source_row = ttk.Frame(folder_frame)
        source_row.pack(fill=tk.X, pady=5)
        ttk.Label(source_row, text="Source:", width=12).pack(side=tk.LEFT)
        ttk.Entry(source_row, textvariable=self.source_path, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ttk.Button(source_row, text="Browse...", command=self.browse_source).pack(side=tk.LEFT)

        # Destination folder
        dest_row = ttk.Frame(folder_frame)
        dest_row.pack(fill=tk.X, pady=5)
        ttk.Label(dest_row, text="Destination:", width=12).pack(side=tk.LEFT)
        ttk.Entry(dest_row, textvariable=self.dest_path, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ttk.Button(dest_row, text="Browse...", command=self.browse_destination).pack(side=tk.LEFT)

        # Options
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10")
        options_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(options_frame, text="Renumber to match destination's pattern:").pack(anchor=tk.W)
        renumber_row = ttk.Frame(options_frame)
        renumber_row.pack(anchor=tk.W, padx=(20, 0))
        for label, key in (("Images", "image"), ("Videos", "video"),
                           ("Audio", "audio"), ("Documents", "document")):
            ttk.Checkbutton(renumber_row, text=label, variable=self.renumber_vars[key]).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(options_frame, text="When destination already has a file with the same name:").pack(anchor=tk.W, pady=(8, 0))
        ttk.Combobox(
            options_frame,
            textvariable=self.collision_label,
            values=[label for label, _ in self._collision_options],
            state='readonly',
            width=50,
        ).pack(anchor=tk.W, padx=(20, 0))

        ttk.Checkbutton(
            options_frame,
            text="Include all files (ignore extension filter — copies anything, unknown types keep original names)",
            variable=self.include_all
        ).pack(anchor=tk.W, pady=(8, 0))

        # Preview frame
        preview_frame = ttk.LabelFrame(main_frame, text="Preview", padding="10")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Preview text area with scrollbar
        self.preview_text = scrolledtext.ScrolledText(
            preview_frame,
            height=12,
            font=("Consolas", 10),
            state=tk.DISABLED,
            background=PALETTE['panel'],
            foreground=PALETTE['text'],
            insertbackground=PALETTE['accent'],
            borderwidth=1,
            relief='solid',
            highlightthickness=0,
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True)

        # Configure tags for coloring
        self.preview_text.tag_config("arrow", foreground=PALETTE['accent'])
        self.preview_text.tag_config("filename", foreground=PALETTE['text'])
        self.preview_text.tag_config("folder", foreground="#6b7a8c")

        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(0, 10))
        self.progress.pack_forget()

        # Status label
        self.status_label = ttk.Label(main_frame, text="Select source and destination folders to preview.", font=("Segoe UI", 9))
        self.status_label.pack(fill=tk.X, pady=(0, 10))

        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        self.check_dupes_btn = ttk.Button(
            button_frame,
            text="Check Duplicates",
            command=self.check_duplicates
        )
        self.check_dupes_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.remove_dupes_btn = ttk.Button(
            button_frame,
            text="Remove Duplicates from Source",
            command=self.remove_duplicates,
            state=tk.DISABLED,
            style='Danger.TButton'
        )
        self.remove_dupes_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.preview_btn = ttk.Button(
            button_frame,
            text="Preview",
            command=self.generate_preview
        )
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.sync_btn = ttk.Button(
            button_frame,
            text="Sync Now",
            command=self.execute_sync,
            state=tk.DISABLED
        )
        self.sync_btn.pack(side=tk.LEFT)

        ttk.Button(button_frame, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(button_frame, text="Close", command=self.root.destroy, style='Neutral.TButton').pack(side=tk.RIGHT)

    def _persist_paths(self):
        save_state({
            'source': self.source_path.get().strip(),
            'destination': self.dest_path.get().strip(),
        })

    def browse_source(self):
        initial = self.source_path.get().strip() or os.path.expanduser("~")
        folder = filedialog.askdirectory(title="Select Source Folder", initialdir=initial)
        if folder:
            self.source_path.set(folder)
            self._persist_paths()

    def browse_destination(self):
        initial = self.dest_path.get().strip() or os.path.expanduser("~")
        folder = filedialog.askdirectory(title="Select Destination Folder", initialdir=initial)
        if folder:
            self.dest_path.set(folder)
            self._persist_paths()

    def _update_preview(self, text: str):
        """Thread-safe preview update"""
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete(1.0, tk.END)
        self.preview_text.insert(tk.END, text)
        self.preview_text.config(state=tk.DISABLED)

    def _set_status(self, text: str):
        """Thread-safe status update"""
        self.status_label.config(text=text)

    def _validate_folders(self) -> Optional[Tuple[str, str]]:
        source = self.source_path.get().strip()
        destination = self.dest_path.get().strip()
        if not source:
            messagebox.showwarning("Missing Source", "Please select a source folder.")
            return None
        if not destination:
            messagebox.showwarning("Missing Destination", "Please select a destination folder.")
            return None
        if not os.path.isdir(source):
            messagebox.showerror("Invalid Source", "Source folder does not exist.")
            return None
        if not os.path.isdir(destination):
            messagebox.showerror("Invalid Destination", "Destination folder does not exist.")
            return None
        self._persist_paths()
        return source, destination

    def check_duplicates(self):
        folders = self._validate_folders()
        if not folders:
            return
        source, destination = folders

        self._set_status("Scanning for duplicates with fdupes...")
        self.check_dupes_btn.config(state=tk.DISABLED)
        self.remove_dupes_btn.config(state=tk.DISABLED)

        def do_scan():
            try:
                groups = find_cross_duplicates(source, destination)
            except FileNotFoundError:
                self.root.after(0, lambda: messagebox.showerror(
                    "fdupes Not Found",
                    "fdupes is not installed or not on PATH."))
                self.root.after(0, lambda: self._set_status("Duplicate scan failed."))
                self.root.after(0, lambda: self.check_dupes_btn.config(state=tk.NORMAL))
                return
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Scan Error", f"Failed to scan duplicates:\n{e}"))
                self.root.after(0, lambda: self._set_status("Duplicate scan failed."))
                self.root.after(0, lambda: self.check_dupes_btn.config(state=tk.NORMAL))
                return

            self.root.after(0, lambda: self._show_duplicates(groups, source, destination))

        threading.Thread(target=do_scan, daemon=True).start()

    def _show_duplicates(self, groups: List[Dict[str, List[str]]], source: str, destination: str):
        self.duplicate_groups = groups
        self.check_dupes_btn.config(state=tk.NORMAL)

        if not groups:
            self._update_preview("No duplicates found between source and destination.")
            self._set_status("No cross-folder duplicates found.")
            self.remove_dupes_btn.config(state=tk.DISABLED)
            return

        src_count = sum(len(g['source']) for g in groups)
        lines = [f"Found {len(groups)} duplicate group(s) — {src_count} source file(s) already in destination:\n"]
        for i, group in enumerate(groups, 1):
            lines.append(f"Group {i}:")
            for f in group['source']:
                rel = os.path.relpath(f, source)
                lines.append(f"  [Source] {rel}")
            for f in group['dest']:
                rel = os.path.relpath(f, destination)
                lines.append(f"  [Dest]   {rel}")
            lines.append("")

        self._update_preview("\n".join(lines))
        self._set_status(f"{src_count} source file(s) are duplicates of destination files.")
        self.remove_dupes_btn.config(state=tk.NORMAL)

    def remove_duplicates(self):
        if not self.duplicate_groups:
            return
        src_files = [f for g in self.duplicate_groups for f in g['source']]
        if not messagebox.askyesno(
            "Confirm Removal",
            f"Delete {len(src_files)} duplicate file(s) from source?\n\n"
            "These files already exist (byte-identical) in destination."
        ):
            return

        deleted = 0
        errors = []
        for f in src_files:
            try:
                os.remove(f)
                deleted += 1
            except OSError as e:
                errors.append(f"{Path(f).name}: {e}")

        self.duplicate_groups = []
        self.remove_dupes_btn.config(state=tk.DISABLED)
        if errors:
            self._set_status(f"Deleted {deleted}, failed {len(errors)}.")
            messagebox.showwarning(
                "Removal Complete",
                f"Deleted: {deleted}\nErrors: {len(errors)}\n\n" + "\n".join(errors[:10]))
        else:
            self._set_status(f"Removed {deleted} duplicate file(s) from source.")
            messagebox.showinfo("Removal Complete", f"Deleted {deleted} duplicate file(s) from source.")
        self._update_preview("")

    def generate_preview(self):
        folders = self._validate_folders()
        if not folders:
            return
        source, destination = folders

        # Generate preview
        self._set_status("Generating preview...")
        self.preview_btn.config(state=tk.DISABLED)

        try:
            renumber = {k: v.get() for k, v in self.renumber_vars.items()}
            label = self.collision_label.get()
            collision = next((key for lbl, key in self._collision_options if lbl == label), 'version')
            self.plan, _, skipped, skipped_by_ext, conflicts = plan_sync(
                source, destination,
                include_all=self.include_all.get(),
                renumber=renumber,
                collision=collision,
            )

            if not self.plan:
                msg = "No media files found in source folder."
                if skipped:
                    msg += f"\n\n{skipped} file(s) skipped (unsupported extensions)."
                    msg += " Tick 'Include all files' to copy them too."
                self._update_preview(msg)
                self._set_status("No files to sync.")
                self.sync_btn.config(state=tk.DISABLED)
            else:
                # Build preview text
                lines = []
                for src, dest, _ in self.plan:
                    src_name = Path(src).name
                    dest_name = Path(dest).name
                    src_folder = str(Path(src).parent.relative_to(source))
                    dest_folder = str(Path(dest).parent.relative_to(destination))

                    if src_folder == '.':
                        src_folder = ""
                    if dest_folder == '.':
                        dest_folder = ""

                    # Format with arrows
                    line = f"{src_name}"
                    if src_folder:
                        line = f"[{src_folder}] {src_name}"

                    arrow = " → "
                    dest_line = f"{dest_name}"
                    if dest_folder:
                        dest_line = f"[{dest_folder}] {dest_name}"

                    lines.append(f"  {line}{arrow}{dest_line}")

                total_bytes = 0
                for src, _, _ in self.plan:
                    try:
                        total_bytes += os.path.getsize(src)
                    except OSError:
                        pass
                free_bytes = shutil.disk_usage(destination).free
                size_line = f"Total: {format_size(total_bytes)} — {format_size(free_bytes)} free on destination"
                if total_bytes > free_bytes:
                    size_line = "⚠️ NOT ENOUGH SPACE — " + size_line

                skipped_line = ""
                if skipped:
                    top = sorted(skipped_by_ext.items(), key=lambda kv: -kv[1])[:5]
                    breakdown = ", ".join(f"{ext} ({n})" for ext, n in top)
                    extra = "" if len(skipped_by_ext) <= 5 else f", +{len(skipped_by_ext) - 5} more types"
                    skipped_line = f"Skipped {skipped} unsupported file(s): {breakdown}{extra}\n"

                conflict_line = ""
                if conflicts:
                    conflict_line = f"⚠️ {conflicts} filename conflict(s) — handled per Options: '{label}'\n"

                header = f"Files to sync ({len(lines)} total):\n{size_line}\n{skipped_line}{conflict_line}\n"
                self._update_preview(header + "\n".join(lines))
                if total_bytes > free_bytes:
                    self._set_status(f"⚠️ Need {format_size(total_bytes)} but only {format_size(free_bytes)} free.")
                    self.sync_btn.config(state=tk.DISABLED)
                else:
                    self._set_status(f"Ready: {len(lines)} files, {format_size(total_bytes)}. Click 'Sync Now'.")
                    self.sync_btn.config(state=tk.NORMAL)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate preview:\n{e}")
            self._set_status("Preview generation failed.")

        finally:
            self.preview_btn.config(state=tk.NORMAL)

    def execute_sync(self):
        if not self.plan:
            messagebox.showwarning("No Plan", "Please generate a preview first.")
            return

        # Confirm
        if not messagebox.askyesno("Confirm Sync", f"Copy {len(self.plan)} files?"):
            return

        # Disable UI
        self.sync_btn.config(state=tk.DISABLED)
        self.preview_btn.config(state=tk.DISABLED)
        self.progress.pack(fill=tk.X, pady=(0, 10))
        self.progress['maximum'] = len(self.plan)
        self.progress['value'] = 0

        def do_sync():
            def update_progress(current, total):
                self.root.after(0, lambda: self.progress.config(value=current))

            def update_status(msg):
                self.root.after(0, lambda: self._set_status(msg))

            success, errors, error_msgs, copied_sources = execute_sync(
                self.plan,
                progress_callback=update_progress,
                status_callback=update_status
            )

            # Show results on main thread
            self.root.after(0, lambda: self._show_results(success, errors, error_msgs, copied_sources))

        # Run in thread
        self._set_status("Syncing...")
        threading.Thread(target=do_sync, daemon=True).start()

    def _show_results(self, success: int, errors: int, error_msgs: List[str], copied_sources: List[str]):
        self.progress.pack_forget()
        self.preview_btn.config(state=tk.NORMAL)

        if errors == 0:
            self._set_status(f"✅ Success! {success} files copied.")
            messagebox.showinfo("Sync Complete", f"✅ All {success} files copied successfully!")
        else:
            self._set_status(f"⚠️ Completed with errors: {success} ok, {errors} failed")
            error_text = "\n".join(error_msgs[:10])
            if len(error_msgs) > 10:
                error_text += f"\n... and {len(error_msgs) - 10} more errors"
            messagebox.showwarning("Sync Complete",
                f"Copied: {success}\nErrors: {errors}\n\n{error_text}")

        self.plan = []
        self.sync_btn.config(state=tk.DISABLED)

        # Offer to delete the successfully-copied source files
        if copied_sources and messagebox.askyesno(
            "Delete Source Files?",
            f"{len(copied_sources)} file(s) copied. Delete them from the source folder?\n\n"
            "Subfolders will be preserved — only files are removed."
        ):
            self._delete_source_files(copied_sources)

    def _delete_source_files(self, files: List[str]):
        deleted = 0
        errors = []
        for f in files:
            try:
                os.remove(f)
                deleted += 1
            except OSError as e:
                errors.append(f"{Path(f).name}: {e}")

        if errors:
            self._set_status(f"Deleted {deleted} from source, {len(errors)} failed.")
            messagebox.showwarning(
                "Source Cleanup",
                f"Deleted: {deleted}\nErrors: {len(errors)}\n\n" + "\n".join(errors[:10]))
        else:
            self._set_status(f"Deleted {deleted} file(s) from source.")
            messagebox.showinfo("Source Cleanup", f"Deleted {deleted} file(s) from source. Folders preserved.")

    def clear_all(self):
        self.source_path.set("")
        self.dest_path.set("")
        self.plan = []
        self.duplicate_groups = []
        self._update_preview("")
        self._set_status("Select source and destination folders to preview.")
        self.sync_btn.config(state=tk.DISABLED)
        self.remove_dupes_btn.config(state=tk.DISABLED)
        self.progress.pack_forget()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = FolderSyncApp(root)
    root.mainloop()
