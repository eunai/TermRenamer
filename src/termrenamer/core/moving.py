"""Apply's moves, which never replace anything (spec #16, section H).

Every new name is claimed by the call that makes it, and that call fails when anything
is at the name, links not followed: a hard link, a file opened with exclusive create, a
symbolic link, a folder made, or on Windows :func:`os.rename`. There is no check before
the move that the move relies on, no ``shutil.move`` and no ``os.replace``. Each change is
recorded in :class:`Changes` at the moment the call that made it succeeds.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from termrenamer.core.collisions import is_case_only_rename
from termrenamer.core.models import Move, PlanFingerprint
from termrenamer.core.paths import claim_key

_LOG = logging.getLogger(__name__)

_NO_HARD_LINK = frozenset({errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP})
"""Why a hard link can fail other than a taken name: another drive, or a filesystem with
no hard links (exFAT, many network shares)."""

_CHUNK = 1 << 20
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)


class FolderMoveFailed(OSError):
    """A child of a folder could not be moved; what moved before it stays moved, and the
    rest stays in the source folder."""


@dataclass
class Changes:
    """Every change one Apply made, each recorded when the call that made it succeeded."""

    moves: list[Move] = field(default_factory=list)
    folders_created: list[Path] = field(default_factory=list)
    folders_removed: list[Path] = field(default_factory=list)
    files_left_behind: list[Path] = field(default_factory=list)

    def make_folders(self, folder: Path) -> None:
        """Make ``folder`` and each missing folder above it, recording each one made."""
        missing: list[Path] = []
        current = folder
        while not current.exists(follow_symlinks=False) and current.parent != current:
            missing.append(current)
            current = current.parent
        for path in reversed(missing):
            try:
                os.mkdir(path)
            except FileExistsError:
                continue
            self.folders_created.append(path)

    def moved(self, source: Path, dest: Path, before: PlanFingerprint) -> None:
        """Record a file moved, with its size and modification time at its new place;
        when that cannot be read, the values read at the old place before the move."""
        try:
            after = _fingerprint(dest)
        except OSError as exc:
            _LOG.warning("Cannot read %s after moving it there: %s", dest, exc)
            after = replace(before, path=dest)
        self.moves.append(Move(source=source, destination=dest, fingerprint=after))


def move_no_replace(source: Path, dest: Path, changes: Changes) -> None:
    """Move ``source`` (a file, a symbolic link moved as itself, or a folder) to ``dest``
    without ever replacing anything there, and record each change in ``changes``.

    - A case-only rename (:func:`~termrenamer.core.collisions.is_case_only_rename`) is a
      plain :func:`os.rename`; afterwards the folder must list the new name.
    - A file on Windows: :func:`os.rename`, which refuses a taken name.
    - A file elsewhere: a hard link at ``dest``, then the source unlinked.
    - When that cannot be made for a reason other than a taken name (another drive, a
      filesystem with no hard links): a copy into a file opened with exclusive create,
      checked against the source, then the source unlinked. A symbolic link is made
      again at ``dest`` and the source unlinked.
    - A folder, on every system: ``dest`` is made, then each child is moved by these
      rules in name order, then the emptied source folder is removed.

    Apply cannot defend a name it has claimed against another program that deletes or
    writes over it during the same Apply.

    Raises:
        FileExistsError: something is at ``dest``; nothing was changed.
        FolderMoveFailed: a child of a folder could not be moved.
        OSError: the move failed; the source is where it was.
    """
    if is_case_only_rename(source, dest):
        _rename_case(source, dest, changes)
    elif stat.S_ISDIR(os.lstat(source).st_mode):
        _move_folder(source, dest, changes)
    else:
        _move_file(source, dest, changes)


def _fingerprint(path: Path, st: os.stat_result | None = None) -> PlanFingerprint:
    st = os.lstat(path) if st is None else st
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)


def _rename_case(source: Path, dest: Path, changes: Changes) -> None:
    before = _fingerprint(source)
    os.rename(source, dest)
    try:
        names = os.listdir(dest.parent)
    except OSError as exc:
        _LOG.warning("Cannot list %s after renaming %s: %s", dest.parent, source, exc)
    else:
        if dest.name not in names:
            raise OSError(errno.EIO, "the folder does not list the new name", str(dest))
    changes.moved(source, dest, before)


def _move_folder(source: Path, dest: Path, changes: Changes) -> None:
    os.mkdir(dest)
    changes.folders_created.append(dest)
    try:
        names = sorted(os.listdir(source), key=lambda name: claim_key(Path(name)))
        for name in names:
            child = source / name
            try:
                if stat.S_ISDIR(os.lstat(child).st_mode):
                    _move_folder(child, dest / name, changes)
                else:
                    _move_file(child, dest / name, changes)
            except FolderMoveFailed:
                raise
            except OSError as exc:
                raise FolderMoveFailed(exc.errno or errno.EIO, f"{child}: {exc}") from exc
        os.rmdir(source)
    except FolderMoveFailed:
        raise
    except OSError as exc:
        raise FolderMoveFailed(exc.errno or errno.EIO, f"{source}: {exc}") from exc
    changes.folders_removed.append(source)


def _move_file(source: Path, dest: Path, changes: Changes) -> None:
    st = os.lstat(source)
    before = _fingerprint(source, st)
    if os.name == "nt":
        try:
            os.rename(source, dest)
        except FileExistsError:
            raise
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _LOG.info("Cannot rename %s -> %s (%s); copying instead", source, dest, exc)
            _copy_then_unlink(source, st, dest, changes)
            return
        changes.moved(source, dest, before)
        return
    try:
        os.link(source, dest, follow_symlinks=False)
    except FileExistsError:
        raise
    except (OSError, NotImplementedError) as exc:
        if isinstance(exc, OSError) and exc.errno not in _NO_HARD_LINK:
            raise
        _LOG.info("Cannot hard-link %s -> %s (%s); copying instead", source, dest, exc)
        _copy_then_unlink(source, st, dest, changes)
        return
    try:
        os.unlink(source)
    except OSError:
        _remove_if_made(dest, st, changes)  # the link is the source's own entry
        raise
    changes.moved(source, dest, before)


def _copy_then_unlink(source: Path, st: os.stat_result, dest: Path, changes: Changes) -> None:
    """Copy ``source`` (as ``st`` found it) to a new file at ``dest``, made with exclusive
    create, check the copy against the source, then unlink the source. On a failure the
    copy is removed while it still is the file made here, and the source stays."""
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(source), dest)
        made = os.lstat(dest)
    else:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY, 0o600)
        made = os.fstat(fd)
        try:
            _copy_into(source, st, fd)
        except BaseException:
            os.close(fd)
            _remove_if_made(dest, made, changes)
            raise
        os.close(fd)
        if os.utime not in os.supports_fd:
            _set_times_by_name(dest, made, st)
    try:
        os.unlink(source)
    except OSError:
        _remove_if_made(dest, made, changes)
        raise
    changes.moved(source, dest, _fingerprint(source, st))


def _copy_into(source: Path, st: os.stat_result, fd: int) -> None:
    """Write the bytes of ``source`` (as ``st`` found it) through ``fd`` and flush them to
    disk; raise when the source changed during the copy or the sizes differ."""
    src = os.open(source, os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    try:
        if not os.path.samestat(os.fstat(src), st):
            raise OSError(errno.EIO, "the source changed before the copy", str(source))
        while chunk := os.read(src, _CHUNK):
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view) :]
        os.fsync(fd)
        if os.chmod in os.supports_fd:
            os.chmod(fd, stat.S_IMODE(st.st_mode))
        if os.utime in os.supports_fd:
            os.utime(fd, ns=(st.st_atime_ns, st.st_mtime_ns))
        written = os.fstat(fd).st_size
        now = os.fstat(src)
    finally:
        os.close(src)
    unchanged = (now.st_size, now.st_mtime_ns) == (st.st_size, st.st_mtime_ns)
    if not unchanged or not os.path.samestat(os.lstat(source), st):
        raise OSError(errno.EIO, "the source changed during the copy", str(source))
    if written != st.st_size:
        raise OSError(errno.EIO, "the copy is not the size of the source", str(source))


def _set_times_by_name(dest: Path, made: os.stat_result, st: os.stat_result) -> None:
    """Give the copy the source's times where no descriptor can (Windows), while ``dest``
    still is the file made here."""
    try:
        if os.path.samestat(os.lstat(dest), made):
            os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError as exc:
        _LOG.warning("Cannot set the times of %s: %s", dest, exc)


def _remove_if_made(dest: Path, made: os.stat_result, changes: Changes) -> None:
    """Remove ``dest`` while it still is the entry made here; record it as left behind
    when it cannot be removed."""
    try:
        if not os.path.samestat(os.lstat(dest), made):
            return
        os.unlink(dest)
    except FileNotFoundError:
        return
    except OSError as exc:
        _LOG.warning("Cannot remove %s, which Apply made: %s", dest, exc)
        changes.files_left_behind.append(dest)
