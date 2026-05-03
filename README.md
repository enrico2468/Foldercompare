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
- **Wide format support**: images (JPG/PNG/GIF/BMP/WebP/AVIF/HEIC/TIFF/SVG/PSD/XCF and RAW formats — CR2, CR3, NEF, ARW, DNG, ORF, RAF, RW2, PEF), videos (MP4/M4V/MOV/AVI/MKV/WebM/WMV/MPG/MPEG/3GP/FLV/OGV/VOB/TS/MTS/M2TS), audio (MP3/M4A/AAC/WAV/FLAC/OGG/Opus/WMA/AIFF), and documents (PDF/DOC/DOCX/XLS/XLSX/PPT/PPTX/ODT/ODS/ODP/TXT/RTF/MD/CSV).
- **Skipped-file visibility**: the preview shows a count and breakdown of files that were filtered out (e.g. unknown extensions), so nothing disappears silently.
- **"Include all files" toggle**: bypasses the extension filter for one-off full copies — unknown file types keep their original names.
- **Per-type renumbering toggles**: independently choose whether images, videos, audio, and documents get renamed to match the destination's numbering pattern, or keep their original filenames. Defaults: images/videos/audio on, documents off.
- **Filename-collision strategy**: when a non-renumbered file would overwrite an existing file in destination, choose what happens — add a version suffix (`file (2).ext`, default), add a date suffix, skip, or overwrite. Conflict count is shown in the preview before sync runs.

## Requirements

- Python 3.8+ (standard library only — no `pip install` needed)
- `tkinter` for the GUI (bundled with Python on macOS/Windows; on Debian/Ubuntu/Mint it's a separate package — `python3-tk`)
- [`fdupes`](https://github.com/adrianlopezroche/fdupes) **or** [`jdupes`](https://codeberg.org/jbruchon/jdupes) on `PATH` for duplicate checking. The app detects either automatically. Without one installed, the sync still works — only the **Check Duplicates** button is disabled.

## Install & run

**Linux (Debian/Ubuntu/Mint):**
```bash
sudo apt install python3 python3-tk fdupes git
git clone https://github.com/enrico2468/Foldercompare.git
cd Foldercompare
python3 Folder_sync_gui.py
```

**macOS:**
```bash
brew install fdupes git
git clone https://github.com/enrico2468/Foldercompare.git
cd Foldercompare
python3 Folder_sync_gui.py
```

**Windows:** install [Python](https://www.python.org/downloads/) (tkinter is bundled), then [`jdupes`](https://codeberg.org/jbruchon/jdupes) for duplicate checking (native Windows builds available; `fdupes` itself has no Windows port). Clone the repo and run `python Folder_sync_gui.py`.

For the CLI version: `python3 Compare_folders.py` (interactive prompts).

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
