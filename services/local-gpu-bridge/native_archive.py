"""Bounded, project-scoped archive extraction without shell commands or metadata restore."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile

MAX_FILES = 100_000
MAX_BYTES = 32 * 1024**3


def validate_request(root, archive_path, destination, strip_components=0, expected_sha256=None):
    from native_control import inside
    if type(strip_components) is not int or not 0 <= strip_components <= 8:
        raise ValueError('strip_components must be an integer from 0 to 8.')
    if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch('[a-fA-F0-9]{64}', expected_sha256)):
        raise ValueError('expected_sha256 must contain 64 hexadecimal characters.')
    source, target = inside(root, archive_path), inside(root, destination)
    if not source.is_file():
        raise ValueError('Project archive was not found.')
    if not source.name.lower().endswith(('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz', '.tar.zst')):
        raise ValueError('Supported archives: zip, tar, tar.gz, tgz, tar.bz2, tar.xz, tar.zst.')
    if target.exists() or target.is_symlink():
        raise ValueError('Destination already exists; choose a new directory. Nothing was overwritten.')
    if not target.parent.is_dir():
        raise ValueError('Destination parent directory must already exist.')
    return source, target


def extract_archive(root, archive_path, destination, strip_components=0, expected_sha256=None,
                    *, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    from native_control import clean_relative, inside
    root = Path(root).resolve()
    source, target = validate_request(root, archive_path, destination, strip_components, expected_sha256)
    # Work from one open descriptor so a replaced archive cannot bypass the checksum.
    with source.open('rb') as archive:
        if expected_sha256:
            checksum = hashlib.file_digest(archive, 'sha256').hexdigest()
            if checksum != expected_sha256.lower():
                raise ValueError('Archive SHA-256 does not match; extraction was not started.')
            archive.seek(0)
        stage = Path(tempfile.mkdtemp(prefix='.archive-', dir=target.parent))
        files = entries = total = 0
        seen, explicit = {}, set()

        def output(name, size, directory):
            nonlocal entries, total, files
            entries += 1
            if entries > max_files:
                raise ValueError('Archive has too many entries.')
            # Validate BEFORE stripping, including drive names, ADS and protected paths.
            name = name.rstrip('/') if directory else name
            clean_relative(name)
            if any(ord(c) < 32 or c in '<>"|?*' for c in name):
                raise ValueError('Archive contains an invalid filename.')
            parts = name.split('/')[strip_components:]
            if not parts:
                if directory:
                    return None
                raise ValueError('strip_components would discard a file.')
            relative = '/'.join(parts)
            clean_relative(relative)
            key = relative.casefold()
            if key in explicit:
                raise ValueError('Archive contains duplicate or conflicting paths.')
            explicit.add(key)
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index])
                kind = 'dir' if index < len(parts) or directory else 'file'
                previous = seen.setdefault(prefix.casefold(), (prefix, kind))
                if previous != (prefix, kind):
                    raise ValueError('Archive contains duplicate or conflicting paths.')
            dest = inside(stage, relative)
            if directory:
                dest.mkdir(parents=True, exist_ok=True)
                return None
            if size < 0 or total + size > max_bytes:
                raise ValueError('Archive exceeds the extracted size limit.')
            if shutil.disk_usage(stage).free < size + 64 * 1024**2:
                raise ValueError('Insufficient disk space for extraction.')
            total += size
            files += 1
            dest.parent.mkdir(parents=True, exist_ok=True)
            return dest

        def copy(reader, dest, size):
            remaining = size
            with reader, dest.open('xb') as writer:
                while remaining:
                    block = reader.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError('Archive is truncated.')
                    writer.write(block)
                    remaining -= len(block)
                if reader.read(1):
                    raise ValueError('Archive entry exceeds its declared size.')

        try:
            if source.name.lower().endswith('.zip'):
                with zipfile.ZipFile(archive) as bundle:
                    for member in bundle.infolist():
                        mode = member.external_attr >> 16
                        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or member.flag_bits & 1:
                            raise ValueError('Archive links, special files and encrypted entries are not supported.')
                        dest = output(member.filename, member.file_size, member.is_dir())
                        if dest is not None:
                            copy(bundle.open(member), dest, member.file_size)
            else:
                with tarfile.open(fileobj=archive, mode='r|*') as bundle:
                    for member in bundle:
                        if not (member.isfile() or member.isdir()) or member.sparse is not None:
                            raise ValueError('Archive links, special files and sparse files are not supported.')
                        dest = output(member.name, member.size, member.isdir())
                        if dest is not None:
                            copy(bundle.extractfile(member), dest, member.size)
            if not files:
                raise ValueError('Archive contains no files to extract.')
            # No timestamps, owners or permissions from the archive are restored.
            validate_request(root, archive_path, destination, strip_components, expected_sha256)
            os.rename(stage, target)
            return {'destination': destination, 'files': files, 'entries': entries, 'bytes': total}
        except (tarfile.TarError, zipfile.BadZipFile, EOFError) as exc:
            raise ValueError('Archive is corrupt or uses unsupported compression.') from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)
