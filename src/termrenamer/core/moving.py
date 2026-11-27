"""Apply's moves, which never replace anything (spec #16, section H).

Every new name is claimed by the call that makes it, and that call fails when anything
is at the name, links not followed: a hard link, a file opened with exclusive create, a
symbolic link, a folder made, or on Windows :func:`os.rename`. On Windows an exclusive
create follows a link at the name, so a copy is made there under a fresh name and
claimed by that rename; and the rename takes a name that is the source's own file
(another letter case of its name, a separate hard link of it), so that one name is
refused by a check directly before it. There is no ``shutil.move`` and no
``os.replace``. Each change is recorded in :class:`Changes` at the moment the call that
made it succeeds, before any call that can raise. A symbolic link or a Windows junction
is never entered: it is moved as itself, and nothing behind it is read, moved or removed.

Apply checks a source and claims a destination by calls that sit directly before the
change they guard. It cannot defend against another program that changes that same file
or name between such a check and the very next call, or that deletes or writes over a
name Apply has claimed.
"""

from __future__ import annotations

import errno
import logging
import os
import secrets
import stat
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from termrenamer.core.collisions import is_case_only_rename
from termrenamer.core.models import Move, PlanFingerprint
from termrenamer.core.paths import claim_key

_LOG = logging.getLogger(__name__)

_NO_HARD_LINK = frozenset({errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP})
"""Why a hard link can fail other than a taken name: another drive, or a filesystem with
no hard links (exFAT, many network shares)."""

_LINK_TAGS = frozenset(
    {
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
    }
)
"""The reparse tags of a Windows symbolic link and of a junction."""

_CHUNK = 1 << 20
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class FolderMoveFailed(OSError):
    """A child of a folder could not be moved; what moved before it stays moved, and the
    rest stays in the source folder."""


class NotAsRecorded(OSError):
    """The file at the source is not the one recorded: its size or modification time
    differs, or it is a folder; nothing was changed."""


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
        """Record a file moved, with its size and modification time at its new place.

        The move is recorded first, with the values read at the old place before the
        move; they are replaced by the new place's when it can be read, so no error
        reading it can lose the move.
        """
        self.moves.append(
            Move(source=source, destination=dest, fingerprint=replace(before, path=dest))
        )
        try:
            after = _fingerprint(dest)
        except Exception as exc:
            _LOG.warning("Cannot read %s after moving it there: %s", dest, exc)
            return
        self.moves[-1] = Move(source=source, destination=dest, fingerprint=after)


def move_no_replace(
    source: Path, dest: Path, changes: Changes, *, expected: PlanFingerprint | None = None
) -> None:
    """Move ``source`` (a file, a symbolic link moved as itself, or a folder) to ``dest``
    without ever replacing anything there, and record each change in ``changes``.

    - A case-only rename (:func:`~termrenamer.core.collisions.is_case_only_rename`) is a
      plain :func:`os.rename`; afterwards the folder must list the new name.
    - A file on Windows: :func:`os.rename`, which refuses a taken name; a name that is
      the source's own file, which that rename would take, is refused just before it.
    - A file elsewhere: a hard link at ``dest``, then the source unlinked.
    - When that cannot be made for a reason other than a taken name (another drive, a
      filesystem with no hard links): a copy into a file opened with exclusive create,
      checked against the source, then the source unlinked. A symbolic link is made
      again at ``dest`` and the source unlinked. On Windows the copy is made under a
      fresh name beside ``dest``, then renamed to ``dest``.
    - A folder, on every system: ``dest`` is made, then each child is moved by these
      rules in name order, then the emptied source folder is removed.

    With ``expected`` (Undo's moves, each of a file or a link), the source must be no
    folder and have the recorded size and modification time, read with ``lstat`` as the
    last call before the rename or the hard link.

    Apply cannot defend a name it has claimed against another program that deletes or
    writes over it during the same Apply.

    Raises:
        FileExistsError: something is at ``dest``; nothing was changed.
        NotAsRecorded: the source is not as ``expected``; nothing was changed.
        FolderMoveFailed: a child of a folder could not be moved.
        OSError: the move failed; the source is where it was.
    """
    before = _fingerprint(source)
    if is_case_only_rename(source, dest):
        if expected is not None:
            _check(source, os.lstat(source), expected)  # the last call before the rename
        _rename_case(source, dest, before, changes)
    elif is_folder(source, st := os.lstat(source)):
        if expected is not None:
            _check(source, st, expected)
        _move_folder(source, dest, changes)
    else:
        _move_file(source, dest, changes, expected)


def is_link(path: Path, st: os.stat_result) -> bool:
    """Whether ``path`` (``st`` its ``lstat``) is a symbolic link or a Windows junction,
    which Apply moves as itself and never enters."""
    if stat.S_ISLNK(st.st_mode) or os.path.isjunction(path):
        return True
    return getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def is_folder(path: Path, st: os.stat_result) -> bool:
    """Whether ``path`` (``st`` its ``lstat``) is a folder Apply moves as its files: a
    folder that is not a link or a junction."""
    return stat.S_ISDIR(st.st_mode) and not is_link(path, st)


def leave_folder(folder: Path) -> None:
    """Change the working folder to ``folder``'s parent when it is ``folder`` or inside
    it, so ``folder`` can be removed; a working folder that cannot be read is left."""
    try:
        cwd = Path(os.getcwd())
        target = os.lstat(folder)
        # By identity, not by text: the Plan may spell the folder in another letter case.
        inside = any(os.path.samestat(os.stat(p), target) for p in (cwd, *cwd.parents))
    except OSError:
        return
    if inside:
        try:
            os.chdir(folder.parent)
        except OSError as exc:
            _LOG.warning("Could not leave %s before removing it: %s", folder, exc)


def _check(source: Path, st: os.stat_result, expected: PlanFingerprint) -> None:
    """Raise :class:`NotAsRecorded` unless ``st`` (the source's ``lstat``) is no folder and
    has ``expected``'s size and modification time."""
    if is_folder(source, st):
        raise NotAsRecorded(errno.EISDIR, "a folder is there now", str(source))
    if (st.st_size, st.st_mtime_ns) != (expected.size, expected.mtime_ns):
        msg = "its size or modification time changed"
        raise NotAsRecorded(errno.EIO, msg, str(source))


def _fingerprint(path: Path, st: os.stat_result | None = None) -> PlanFingerprint:
    st = os.lstat(path) if st is None else st
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)


def _rename_case(source: Path, dest: Path, before: PlanFingerprint, changes: Changes) -> None:
    """A case-only rename; the rename is recorded once made, and fails unless the folder
    then lists the new name exactly."""
    os.rename(source, dest)
    changes.moved(source, dest, before)
    try:
        names = os.listdir(dest.parent)
    except OSError as exc:
        msg = f"the new name could not be confirmed: {exc}"
        raise OSError(errno.EIO, msg, str(dest)) from exc
    if dest.name not in names:
        msg = "the new name could not be confirmed: the folder does not list it"
        raise OSError(errno.EIO, msg, str(dest))


def _move_folder(source: Path, dest: Path, changes: Changes) -> None:
    os.mkdir(dest)
    changes.folders_created.append(dest)
    try:
        names = sorted(os.listdir(source), key=lambda name: claim_key(Path(name)))
        for name in names:
            child = source / name
            try:
                if is_folder(child, os.lstat(child)):
                    _move_folder(child, dest / name, changes)
                else:
                    _move_file(child, dest / name, changes)
            except FolderMoveFailed:
                raise
            except OSError as exc:
                raise FolderMoveFailed(exc.errno or errno.EIO, f"{child}: {exc}") from exc
        leave_folder(source)
        os.rmdir(source)
    except FolderMoveFailed:
        raise
    except OSError as exc:
        raise FolderMoveFailed(exc.errno or errno.EIO, f"{source}: {exc}") from exc
    changes.folders_removed.append(source)


def _move_file(
    source: Path, dest: Path, changes: Changes, expected: PlanFingerprint | None = None
) -> None:
    """Move a file, a symbolic link or a junction as itself; with ``expected``, only while
    it is as recorded (:func:`_check`, the last call before the rename or hard link)."""
    st = os.lstat(source)
    if expected is not None:
        _check(source, st, expected)
    before = _fingerprint(source, st)
    if os.name == "nt":
        _refuse_the_source_itself(dest, st)  # the last call before the rename
        try:
            os.rename(source, dest)
        except FileExistsError:
            raise
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _LOG.info("Cannot rename %s -> %s (%s); copying instead", source, dest, exc)
            _copy_then_unlink(source, st, dest, before, changes)
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
        _copy_then_unlink(source, st, dest, before, changes)
        return
    changes.files_left_behind.append(dest)  # until the source's name is removed
    made = os.lstat(dest)
    _unlink_source(source, dest, made, lambda now: os.path.samestat(now, made), before, changes)


def _unlink_source(
    source: Path,
    dest: Path,
    made: os.stat_result,
    still_the_source: Callable[[os.stat_result], bool],
    before: PlanFingerprint,
    changes: Changes,
) -> None:
    """Remove the source's name now that ``dest`` (``made`` here, listed as left behind)
    holds it. The check by name is the last call before the unlink: when the source is
    no longer what was moved, ``dest`` is removed instead and the source stays."""
    try:
        if not still_the_source(os.lstat(source)):
            raise OSError(errno.EIO, "the source changed during its move", str(source))
        os.unlink(source)
    except BaseException:
        _remove_if_made(dest, made, changes)
        raise
    _forget(changes.files_left_behind, dest)
    changes.moved(source, dest, before)


def _copy_then_unlink(
    source: Path, st: os.stat_result, dest: Path, before: PlanFingerprint, changes: Changes
) -> None:
    """Copy ``source`` (as ``st`` found it) to a new name at ``dest``, check the copy, then
    unlink the source. On a failure the copy is removed while it still is the one made
    here, and listed as left behind when it cannot be.

    Elsewhere the copy is made at ``dest`` by a call that fails when anything is there,
    links not followed. On Windows an exclusive create follows a link at the name, so
    the copy is made under a fresh name beside ``dest`` and then claimed by
    :func:`os.rename`, which refuses every name that exists, a link included.
    """
    if is_link(source, st) and not stat.S_ISLNK(st.st_mode):
        msg = "a junction cannot be moved to another drive"
        raise OSError(errno.EXDEV, msg, str(source))
    if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
        # A pipe, a socket or a device is never opened: reading one could block or never end.
        msg = "only a file or a symbolic link can be copied to another drive"
        raise OSError(errno.EXDEV, msg, str(source))
    if os.name == "nt":
        part = _fresh_name(dest)
        made = _make_copy(source, st, part, changes)
        try:
            os.rename(part, dest)
        except BaseException:
            _remove_if_made(part, made, changes)
            raise
        changes.files_left_behind.append(dest)
        _forget(changes.files_left_behind, part)
    else:
        made = _make_copy(source, st, dest, changes)

    def unchanged(now: os.stat_result) -> bool:
        return os.path.samestat(now, st) and (now.st_size, now.st_mtime_ns) == (
            st.st_size,
            st.st_mtime_ns,
        )

    _unlink_source(source, dest, made, unchanged, before, changes)


def _make_copy(source: Path, st: os.stat_result, at: Path, changes: Changes) -> os.stat_result:
    """Make a copy of ``source`` (as ``st`` found it) at the new name ``at``, list ``at``
    as left behind from the moment it is made, and return the copy's ``lstat``."""
    if stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(source), at)
        changes.files_left_behind.append(at)
        made = os.lstat(at)
    else:
        fd = os.open(at, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY, 0o600)
        changes.files_left_behind.append(at)
        try:
            made = os.fstat(fd)
        except BaseException:
            _close(fd)
            raise
        try:
            _copy_into(source, st, fd)
        except BaseException:
            _close(fd)
            _remove_if_made(at, made, changes)
            raise
        try:
            os.close(fd)
        except BaseException:
            _remove_if_made(at, made, changes)
            raise
        if os.utime not in os.supports_fd:
            _set_times_by_name(at, made, st)
    if not os.path.samestat(os.lstat(at), made):
        raise OSError(errno.EIO, "the copy is not at the name it was made at", str(at))
    return made


def _fresh_name(dest: Path) -> Path:
    """A name beside ``dest`` that nothing has, for a copy to be made under before it is
    claimed at ``dest``."""
    while True:
        part = dest.with_name(f".termrenamer-{secrets.token_hex(8)}.part")
        if not os.path.lexists(part):
            return part


def _refuse_the_source_itself(dest: Path, st: os.stat_result) -> None:
    """Raise :class:`FileExistsError` when ``dest`` is the source's own entry (``st`` its
    ``lstat``), under another letter case of its name or as a separate hard link of it.

    Windows's :func:`os.rename` refuses every other name that exists, but takes one that
    is the source itself, so that one name is refused here.
    """
    try:
        there = os.lstat(dest)
    except OSError:
        return  # nothing there, or nothing readable: the rename refuses what exists
    if os.path.samestat(there, st):
        raise FileExistsError(errno.EEXIST, "the new name is the source's own file", str(dest))


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError as exc:
        _LOG.warning("Cannot close a file Apply was copying: %s", exc)


def _forget(paths: list[Path], path: Path) -> None:
    if path in paths:
        paths.remove(path)


def _copy_into(source: Path, st: os.stat_result, fd: int) -> None:
    """Write the bytes of ``source`` (as ``st`` found it) through ``fd`` and flush them to
    disk; raise when the source changed during the copy or the sizes differ."""
    # Non-blocking, so a source swapped for a pipe since it was read cannot hold Apply.
    src = os.open(source, os.O_RDONLY | _O_NOFOLLOW | _O_BINARY | _O_NONBLOCK)
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
    if (now.st_size, now.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
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
    """Remove ``dest`` while it still is the entry made here, and take it off the files
    left behind; it stays listed when it cannot be removed."""
    try:
        if os.path.samestat(os.lstat(dest), made):
            os.unlink(dest)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _LOG.warning("Cannot remove %s, which Apply made: %s", dest, exc)
        return
    _forget(changes.files_left_behind, dest)
