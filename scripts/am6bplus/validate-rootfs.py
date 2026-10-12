#!/usr/bin/env python3
"""Reject unsafe OpenWrt tar layouts before privileged extraction."""
import pathlib, posixpath, sys, tarfile


def validate(filename):
    with tarfile.open(filename, 'r:gz') as archive:
        members = archive.getmembers()
        entries = {}
        for member in members:
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise SystemExit(f'Unsafe rootfs member: {member.name}')
            name = str(path)
            if name in entries:
                raise SystemExit(f'Duplicate rootfs member: {name}')
            entries[name] = member
        for name, member in entries.items():
            # Never let tar write through an archived symlink/hardlink parent.
            for parent in pathlib.PurePosixPath(name).parents:
                target = entries.get(str(parent))
                if target is not None and not target.isdir():
                    raise SystemExit(f'Non-directory archive parent: {name}')
            if member.issym():
                # Rootfs absolute links are legitimate (e.g. /etc -> /tmp targets).
                # No other archive entry is allowed to descend through them above.
                target = member.linkname
                if not target.startswith('/'):
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                    if target == '..' or target.startswith('../'):
                        raise SystemExit(f'Escaping rootfs symlink: {name}')
            elif member.islnk():
                target = pathlib.PurePosixPath(member.linkname)
                if target.is_absolute() or '..' in target.parts:
                    raise SystemExit(f'Unsafe rootfs hardlink: {name}')
                original = entries.get(str(target))
                if original is None or not original.isfile():
                    raise SystemExit(f'Hardlink target is not an archived regular file: {name}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate-rootfs.py ROOTFS_TAR_GZ")
    validate(sys.argv[1])
