# Foldercompare

A small tool to compare two folders, check for duplicates, copy one set to the other while renaming them to the destination's format, and delete the originals.

## Features

- **GUI app** (`Folder_sync_gui.py`): tkinter-based desktop interface.
- **CLI script** (`Compare_folders.py`): same sync logic for the terminal.
- **Duplicate detection**: uses `fdupes` to find byte-identical files between source and destination before copying, so you don't end up with renamed duplicates.
- **Pattern-aware renaming**: detects naming patterns (e.g. `Holiday 1.jpg`, `Holiday 2.jpg`) in the destination and continues numbering for incoming files.
- **Source cleanup**: after a successful sync, optionally deletes the copied files from the source. Subfolders are preserved — only files are removed.
- **Size + free-space preview**: the preview shows total bytes to copy and free space on destination, with a warning if there isn't enough room.
- **Remembers last folders**: the last source/destination pair is saved to `~/.config/foldercompare/state.json` and restored on next launch.

## Requirements

- Python 3.8+ (uses standard library only — `tkinter`, `shutil`, `pathlib`)
- [`fdupes`](https://github.com/adrianlopezroche/fdupes) on `PATH` (Linux/macOS). On Debian/Ubuntu: `sudo apt install fdupes`.

## Usage

```bash
python3 Folder_sync_gui.py     # GUI
python3 Compare_folders.py     # CLI (interactive prompts)
```

In the GUI:

1. Pick a source folder and a destination folder.
2. **Check Duplicates** — runs fdupes; review any cross-folder matches and optionally remove them from source.
3. **Preview** — see the planned copies and renames.
4. **Sync Now** — execute the copy.
5. When prompted, choose whether to delete the now-copied files from source.

## ⚠️ Warning

This tool **deletes files** when you confirm the duplicate-removal or post-sync cleanup prompts. There is no undo. Always sanity-check the preview before confirming, and keep a backup if the source data is irreplaceable.

## License

MIT — see [LICENSE](LICENSE).
