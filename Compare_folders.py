#!/usr/bin/env python3
"""
Generic folder sync script.
Prompts for source & destination, syncs files preserving folder structure
and renumbering files to match destination's naming pattern.
"""

import os
import shutil
import re
from pathlib import Path

# Supported extensions (grouped by type)
IMAGE_EXTS = {
    '.jpg', '.jpeg', '.jfif', '.png', '.gif', '.bmp', '.webp', '.avif',
    '.tiff', '.tif', '.heic', '.heif',
    '.svg', '.psd', '.xcf',
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
SUPPORTED_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS | DOCUMENT_EXTS

def natural_sort_key(filename):
    parts = re.split(r'(\d+)', filename)
    return [int(p) if p.isdigit() else p.lower() for p in parts]

def get_media_type(ext):
    """Return 'image', 'video', 'audio', 'document', or None based on extension."""
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return 'image'
    elif ext in VIDEO_EXTS:
        return 'video'
    elif ext in AUDIO_EXTS:
        return 'audio'
    elif ext in DOCUMENT_EXTS:
        return 'document'
    return None

def get_media_files(folder):
    folder = Path(folder)
    if not folder.exists():
        return []
    files = []
    for item in folder.rglob('*'):
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTS:
            files.append(item)
    return files

def detect_pattern(dest_folder):
    """Detect naming pattern in destination folder. Returns (prefix, highest_number, media_type)."""
    dest_folder = Path(dest_folder)
    if not dest_folder.exists():
        return None, 0, None

    files = [f for f in dest_folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS]

    if not files:
        return None, 0, None

    # Track patterns separately for images and videos
    patterns = {}

    for f in files:
        media_type = get_media_type(f.suffix)
        numbers = re.findall(r'\d+', f.stem)

        if numbers and media_type:
            last_num = numbers[-1]
            potential_prefix = f.stem[:f.stem.rfind(last_num)].rstrip()

            if potential_prefix:
                if media_type not in patterns:
                    patterns[media_type] = {'prefix': potential_prefix, 'max_num': 0}
                patterns[media_type]['max_num'] = max(patterns[media_type]['max_num'], int(last_num))

    # Prefer image pattern if exists, otherwise video
    if 'image' in patterns:
        return patterns['image']['prefix'], patterns['image']['max_num'], 'image'
    elif 'video' in patterns:
        return patterns['video']['prefix'], patterns['video']['max_num'], 'video'

    return None, 0, None

def ask_folder(prompt):
    while True:
        response = input(f"{prompt}: ").strip()
        if not response:
            print("  Please enter a path.")
            continue
        return Path(response).expanduser()

def sync_folders(src, dest, preview_only=False):
    src = Path(src)
    dest = Path(dest)
    results = {'total': 0, 'copied': 0, 'errors': 0}

    src_files = get_media_files(src)

    if not src_files:
        print(f"\n  No media files found in source.")
        return results

    results['total'] = len(src_files)
    to_sync = []

    # Track running number for each (folder, prefix, media_type) combination
    # media_type is 'image' or 'video'
    next_numbers = {}

    for src_file in sorted(src_files, key=lambda x: natural_sort_key(x.name)):
        rel_path = src_file.relative_to(src)
        dest_folder = dest / rel_path.parent
        media_type = get_media_type(src_file.suffix)

        # Detect pattern in destination folder
        pattern_prefix, highest_num, pattern_media_type = detect_pattern(dest_folder)

        # Determine the counter key (folder, prefix, media_type)
        counter_key = (str(dest_folder), pattern_prefix, media_type)

        if counter_key not in next_numbers:
            next_numbers[counter_key] = highest_num + 1

        # Determine action
        dest_file = dest_folder / src_file.name

        if dest_file.exists():
            # Exact file exists - renumber
            if pattern_prefix:
                new_name = f"{pattern_prefix} {next_numbers[counter_key]}{src_file.suffix.lower()}"
                next_numbers[counter_key] += 1
            else:
                new_name = src_file.name
            action = 'rename'
        elif pattern_prefix and media_type == pattern_media_type:
            # Has matching pattern for this media type - apply it
            new_name = f"{pattern_prefix} {next_numbers[counter_key]}{src_file.suffix.lower()}"
            next_numbers[counter_key] += 1
            action = 'pattern'
        else:
            # No pattern or different media type - copy with original name
            new_name = src_file.name
            action = 'copy'

        final_dest = dest_folder / new_name

        to_sync.append({
            'src': src_file,
            'rel_path': rel_path,
            'dest': final_dest,
            'new_name': new_name,
            'action': action,
            'pattern': pattern_prefix,
            'media_type': media_type
        })

    if preview_only:
        print(f"\n  Found {results['total']} file(s) in source\n")
        for item in to_sync:
            if item['action'] == 'copy':
                print(f"  [NEW]     {item['rel_path']}")
            else:
                print(f"  [{item['action'].upper()}] {item['src'].name}")
                print(f"           → {item['new_name']}")
        return results

    # Actually sync
    print()
    for item in to_sync:
        try:
            item['dest'].parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item['src'], item['dest'])

            if item['action'] == 'copy':
                print(f"  ✓ {item['rel_path']}")
            else:
                print(f"  ✓ {item['src'].name}")
                print(f"    → {item['new_name']}")

            results['copied'] += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results['errors'] += 1

    return results

def main():
    print("=" * 60)
    print("FOLDER SYNC")
    print("=" * 60)

    source = ask_folder("Enter SOURCE folder path")
    dest = ask_folder("Enter DESTINATION folder path")

    print("\n" + "-" * 60)
    print(f"Source:      {source}")
    print(f"Destination: {dest}")
    print("-" * 60)

    if not source.exists():
        print(f"\n✗ Source folder does not exist: {source}")
        return

    if not dest.exists():
        print(f"\n✗ Destination folder does not exist: {dest}")
        return

    # Preview first
    print("\n📋 PREVIEW:\n")
    sync_folders(source, dest, preview_only=True)

    print("\n" + "-" * 60)
    response = input("\nProceed with sync? (y/n): ").strip().lower()

    if response != 'y':
        print("Cancelled.")
        return

    print("\n" + "-" * 60)
    print("SYNCING...\n")
    results = sync_folders(source, dest, preview_only=False)

    print("\n" + "=" * 60)
    print(f"Done! {results['copied']} file(s) copied.")
    if results['errors'] > 0:
        print(f"Errors: {results['errors']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
