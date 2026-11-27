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
change they guard: the folders on the way must still be real folders, not links, and
the source must still be of the kind and, for a file, the size and modification time
the Plan recorded. A new name is removed again after a failure only while the source is
verified at its old name, so a file never loses both names. Apply cannot defend against
another program that changes that same file or name between such a check and the very
next call, or that deletes or writes over a name Apply has claimed.

"The same file" never rests on the device and inode number alone, as ext4 and tmpfs give
the number of a file just removed to the next file made (:func:`_one_file`). A file
copied to another drive, and a folder walked, are held open while Apply acts on them
(:class:`_Held`), so that on ext4, tmpfs and other disks that keep an open file's
number its own, no other file can be given their number meanwhile; on Windows a folder
is held by its creation time instead. A source moved by a hard link needs no holding:
its new name keeps the file, and so its number, its own. A symbolic link copied to
another drive is not held: it is told by its times and its target text.
"""

from __future__ import annotations

import errno
import logging
import os
import secrets
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from termrenamer.core.collisions import is_case_only_rename
from termrenamer.core.models import KeptFolder, LinkedFolder, Move, PlanFingerprint
from termrenamer.core.paths import claim_key
from termrenamer.core.scan import is_companion_file

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
    """The source is not as recorded; nothing was changed. ``errno`` says how:
    ``EIO`` its size or modification time differs, ``EISDIR`` a folder is there where a
    file or link was recorded, ``ENOTDIR`` a file or link is there where a folder was."""


class NowALink(OSError):
    """A folder the move goes through or walks, recorded as a real folder, is a link or a
    junction now, or one the Plan found to be a link is no longer that link leading to
    that folder; nothing was moved or made through it."""

    def __init__(self, folder: Path, *, recorded: bool = False) -> None:
        if recorded:
            self.reason = f"the folder {folder} is no longer the link the Plan found"
        else:
            self.reason = f"the folder {folder} is now a link"
        super().__init__(errno.ELOOP, self.reason, str(folder))


_Guard = tuple[Path, "_Held | LinkedFolder | None"]
"""A folder checked at the last look before each call that claims a name through it:
with ``None``, a real folder; with a :class:`_Held`, the very folder found there before;
with a :class:`LinkedFolder`, the very link the Plan found, leading where it led."""

_AtOldName = Callable[[os.stat_result], bool]
"""Whether the source's own file is verified at its old name, given the ``lstat`` of the
old name now."""


def _one_file(a: os.stat_result, b: os.stat_result) -> bool:
    """Whether two looks taken at the same moment see one file: the same device and inode
    number, and the same kind, link count, size and modification time, and elsewhere
    than on Windows the same change time. Two looks at one file agree on all of these,
    so a file given the number of one just removed is told apart whenever it differs in
    any of them; a held file (:class:`_Held`) keeps its number its own anyway.

    Windows is left out of the change time and the permission bits: there a look by name
    and a look through an open file report different change times, and a look by name
    adds the execute bits to a program's name (``.exe``, ``.bat``)."""
    if not os.path.samestat(a, b) or stat.S_IFMT(a.st_mode) != stat.S_IFMT(b.st_mode):
        return False
    fields: tuple[str, ...] = ("st_nlink", "st_size", "st_mtime_ns")
    if os.name != "nt":
        fields += ("st_mode", "st_ctime_ns")
    return all(getattr(a, f) == getattr(b, f) for f in fields)


class _Held:
    """A file or folder Apply holds open while it acts on it, so that no other file can
    be given its inode number while it is held: a file removed while open keeps its
    number until it is closed, and Windows refuses to remove a file held open. A look by
    name sees this file or folder when it agrees with a look through the open descriptor
    (:func:`_one_file`).

    Windows opens no folder, so a folder there is held by its ``lstat`` and creation
    time alone; NTFS gives a removed file's number to no other file. A file is no longer
    verifiable once released.
    """

    def __init__(self, path: Path, st: os.stat_result, *, folder: bool) -> None:
        """Open ``path``, which ``st`` (its ``lstat``) found just before, or raise
        :class:`OSError` when what is opened is not that file or folder:
        :class:`NowALink` for a folder that is a link now."""
        self.st = st
        self.fd: int | None = None
        self.released = False
        if folder and os.name == "nt":
            return
        # Non-blocking, so a source swapped for a pipe since it was read cannot hold Apply.
        flags = os.O_RDONLY | _O_NOFOLLOW | _O_BINARY | _O_NONBLOCK
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            if folder and exc.errno == errno.ELOOP:
                raise NowALink(path) from exc
            raise
        try:
            if not _one_file(os.fstat(fd), st):
                if folder:
                    raise OSError(errno.EIO, "the folder changed during its move", str(path))
                raise OSError(errno.EIO, "the source changed before the copy", str(path))
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def agrees(self, now: os.stat_result) -> bool:
        """Whether ``now``, a look by name taken just before, sees this file or folder."""
        if self.fd is not None:
            try:
                return _one_file(now, os.fstat(self.fd))
            except OSError:
                return False
        if self.released:
            return False
        # A Windows folder, by its number and its creation time.
        made_then = getattr(self.st, "st_birthtime_ns", None)
        return os.path.samestat(now, self.st) and getattr(now, "st_birthtime_ns", None) == made_then

    def descriptor(self) -> int:
        """The open descriptor of a file held, which stays open until released."""
        if self.fd is None:
            raise OSError(errno.EBADF, "the file is no longer held open")
        return self.fd

    def release(self) -> None:
        """Close the descriptor; the file is not verifiable afterwards."""
        self.released = True
        if self.fd is not None:
            fd, self.fd = self.fd, None
            _close(fd)


@dataclass
class Changes:
    """Every change one Apply made, each recorded when the call that made it succeeded."""

    moves: list[Move] = field(default_factory=list)
    folders_created: list[Path] = field(default_factory=list)
    folders_removed: list[Path] = field(default_factory=list)
    files_left_behind: list[Path] = field(default_factory=list)
    folders_kept: list[KeptFolder] = field(default_factory=list)

    def make_folders(
        self,
        folder: Path,
        *,
        real_folders: Sequence[Path] = (),
        links: Sequence[LinkedFolder] = (),
    ) -> None:
        """Make ``folder`` and each missing folder above it, recording each one made.

        Before each folder is made, each folder on the way to it that exists is checked
        (:func:`_guard`): one of ``real_folders`` must be a real folder, and one of
        ``links`` the very link the Plan found; no folder is made where one of ``links``
        was. A check that fails raises :class:`NowALink`, and nothing more is made.
        """
        wanted = [(f, None) for f in real_folders] + [(link.path, link) for link in links]
        missing: list[Path] = []
        current = folder
        while not current.exists(follow_symlinks=False) and current.parent != current:
            missing.append(current)
            current = current.parent
        there: list[_Guard] = [g for g in wanted if g[0] == current or g[0] in current.parents]
        for path in reversed(missing):
            _guard(there)  # the last look before this folder is made in its parent
            if any(isinstance(was, LinkedFolder) for f, was in wanted if f == path):
                raise NowALink(path, recorded=True)  # never a folder where that link was
            try:
                os.mkdir(path)
            except FileExistsError:
                pass  # it appeared meanwhile: checked as any other on the way
            else:
                self.folders_created.append(path)
            there += [g for g in wanted if g[0] == path]
        _guard(there)

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
    source: Path,
    dest: Path,
    changes: Changes,
    *,
    expected: PlanFingerprint | None = None,
    folder: bool | None = None,
    real_folders: Sequence[Path] = (),
    links: Sequence[LinkedFolder] = (),
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
      again at ``dest`` with its kind and target text and the source unlinked. On
      Windows the copy is made under a fresh name beside ``dest``, then renamed to
      ``dest``.
    - A folder, on every system: ``dest`` is made, then each child but a companion file
      (:func:`~termrenamer.core.scan.is_companion_file`) is moved by these rules in name
      order, then the emptied source folder is removed; one left holding only companion
      files is kept. Companion files are left to the filesystem, which may remove,
      write or move them as the files beside them move.

    The last looks before the call that moves are, in this order: each folder of
    ``real_folders`` (and, in a folder's walk, the folder walked and its new folder)
    must be a real folder, not a link or a junction, and each of ``links`` the very
    link the Plan found, leading to the same folder; then the source, read with
    ``lstat``, must be of the kind ``folder`` says (a folder, or a file or link) and,
    with ``expected``, a file or link with the recorded size and modification time.

    Apply cannot defend a name it has claimed against another program that deletes or
    writes over it during the same Apply.

    Raises:
        FileExistsError: something is at ``dest``; nothing was changed.
        NotAsRecorded: the source is not as ``expected`` or ``folder`` says; nothing
            was changed.
        NowALink: a folder of ``real_folders``, or of a folder's walk before anything
            in it moved, is a link or a junction, or one of ``links`` is not the link
            the Plan found; no file was moved.
        FolderMoveFailed: a child of a folder could not be moved; what moved before it
            stays moved and recorded, and the rest stays in the source folder.
        OSError: any other failure. Whatever the error, an interrupt included, the file
            keeps at least one of its two names, and ``changes`` says which: a move in
            ``changes.moves`` means it is at ``dest`` (so also a case-only rename whose
            new name could not be confirmed afterwards, and a source whose old name
            another program removed once ``dest`` held it); ``dest`` in
            ``changes.files_left_behind`` means a copy or link is there beside the
            source; with neither, the source is at its old name and nothing was made,
            but for an interrupt in the instant after the call that makes the new name
            returns and before it is recorded.
    """
    guards: list[_Guard] = [(f, None) for f in real_folders] + [(lf.path, lf) for lf in links]
    if expected is not None:
        folder = False
    if is_case_only_rename(source, dest):
        _guard(guards)
        st = _look(source, expected, folder)  # the last look before the rename
        _rename_case(source, dest, _fingerprint(source, st), changes)
        return
    _guard(guards)
    st = os.lstat(source)
    if folder is not None:
        _check_kind(source, st, folder=folder)
    if is_folder(source, st):
        _move_folder(source, st, dest, changes, guards)
    else:
        _move_file(source, dest, changes, guards, expected)


def folders_between(top: Path, folder: Path) -> list[Path]:
    """Each folder from below ``top`` down to ``folder``, by the recorded text: ``folder``
    alone when it does not lie below ``top``, and none when it is ``top``."""
    if folder == top:
        return []
    if not folder.is_relative_to(top):
        return [folder]
    found, current = [], top
    for part in folder.relative_to(top).parts:
        current = current / part
        found.append(current)
    return found


def links_among(folders: Sequence[Path]) -> list[LinkedFolder]:
    """Each of ``folders`` that is a link or a junction now, as it is now; a folder
    that cannot be read is not one."""
    found = []
    for path in folders:
        try:
            st = os.lstat(path)
            if not is_link(path, st):
                continue
            target, leads_to = os.readlink(path), Path(os.path.realpath(path))
        except OSError:
            continue
        found.append(LinkedFolder(path, st.st_dev, st.st_ino, st.st_mtime_ns, target, leads_to))
    return found


def _is_the_link(folder: Path, st: os.stat_result, was: LinkedFolder) -> bool:
    """Whether ``folder`` (``st`` its ``lstat``) is the link ``was`` recorded: the same
    link, by its device, inode and modification time, with the same target text, leading
    to the same folder."""
    own = (st.st_dev, st.st_ino, st.st_mtime_ns)
    if not is_link(folder, st) or own != (was.device, was.inode, was.modified_ns):
        return False
    try:
        return os.readlink(folder) == was.target and os.path.realpath(folder) == str(was.leads_to)
    except OSError:
        return False


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


def _guard(folders: Sequence[_Guard]) -> None:
    """Raise :class:`NowALink` when a folder of ``folders`` is a link or a junction, or is
    not the link the Plan found, and :class:`OSError` when it is no longer the very
    folder found before."""
    for folder, was in folders:
        st = os.lstat(folder)
        if isinstance(was, LinkedFolder):
            if not _is_the_link(folder, st, was):
                raise NowALink(folder, recorded=True)
            continue
        if is_link(folder, st):
            raise NowALink(folder)
        if was is not None and not was.agrees(st):
            raise OSError(errno.EIO, "the folder changed during its move", str(folder))


def _check_kind(source: Path, st: os.stat_result, *, folder: bool) -> None:
    """Raise unless ``st`` (the source's ``lstat``) is of the kind recorded: a real folder
    (``folder``), or a file or a link; a folder that is now a link is never entered."""
    if folder:
        if is_link(source, st):
            raise NowALink(source)
        if not stat.S_ISDIR(st.st_mode):
            raise NotAsRecorded(errno.ENOTDIR, "a file is there now", str(source))
    elif is_folder(source, st):
        raise NotAsRecorded(errno.EISDIR, "a folder is there now", str(source))


def _look(
    source: Path, expected: PlanFingerprint | None, folder: bool | None = False
) -> os.stat_result:
    """The source's ``lstat``, checked to be of the kind ``folder`` says and, with
    ``expected``, to have its size and modification time."""
    st = os.lstat(source)
    if folder is not None:
        _check_kind(source, st, folder=folder)
    if expected is not None and (st.st_size, st.st_mtime_ns) != (
        expected.size,
        expected.mtime_ns,
    ):
        msg = "its size or modification time changed"
        raise NotAsRecorded(errno.EIO, msg, str(source))
    return st


def _fingerprint(path: Path, st: os.stat_result | None = None) -> PlanFingerprint:
    st = os.lstat(path) if st is None else st
    return PlanFingerprint(path=path, size=st.st_size, mtime_ns=st.st_mtime_ns)


def _rename_case(source: Path, dest: Path, before: PlanFingerprint, changes: Changes) -> None:
    """A case-only rename; the rename is recorded once made, and fails unless the folder
    then lists the new name exactly. A listing that shows only the old name proves the
    rename made no change, so its record is taken off again; a listing that cannot be
    read, or shows neither name, leaves the record, as the rename may have been made."""
    os.rename(source, dest)
    changes.moved(source, dest, before)
    try:
        names = os.listdir(dest.parent)
    except OSError as exc:
        msg = f"the new name could not be confirmed: {exc}"
        raise OSError(errno.EIO, msg, str(dest)) from exc
    if dest.name in names:
        return
    if source.name in names:
        changes.moves[:] = [m for m in changes.moves if (m.source, m.destination) != (source, dest)]
        msg = "the new name was not made: the folder still lists the old name"
        raise OSError(errno.EIO, msg, str(dest))
    msg = "the new name could not be confirmed: the folder does not list it"
    raise OSError(errno.EIO, msg, str(dest))


def _move_folder(
    source: Path, st: os.stat_result, dest: Path, changes: Changes, guards: Sequence[_Guard]
) -> bool:
    """Move the folder ``source`` (``st`` its ``lstat``) as its files: make ``dest``, move
    each child there while ``source`` is still that folder and no folder on the way is a
    link, then remove ``source``. A folder found to be a link after part of the walk
    moved is a :class:`FolderMoveFailed` that says so, not a :class:`NowALink`.

    A companion file (:func:`~termrenamer.core.scan.is_companion_file`) is never moved,
    and one the listing found as a file that the system removed with its file during
    the walk is passed over; any other child that vanishes fails the walk. A folder left
    holding only companion files, and folders this walk kept, is kept: it is not
    removed, as Apply removes no folder that holds a file. A folder that stays, kept or
    after a walk that failed, is recorded in ``changes.folders_kept`` by its device and
    inode number as the walk held it, once the walk moved a file. Return whether
    ``source`` was removed."""
    os.mkdir(dest)
    changes.folders_created.append(dest)
    moved_before = len(changes.moves)
    identity = KeptFolder(source, st.st_dev, st.st_ino)
    held: list[_Held] = []
    try:
        try:
            held.append(_Held(source, st, folder=True))
            held.append(_Held(dest, os.lstat(dest), folder=True))
            inner: list[_Guard] = [*guards, (source, held[0]), (dest, held[1])]
            _guard(inner)
            if not _walk(source, dest, changes, inner, moved_before):
                if len(changes.moves) > moved_before:
                    changes.folders_kept.append(identity)
                return False
            leave_folder(source)
            os.rmdir(source)
        except (FolderMoveFailed, NowALink):
            raise
        except OSError as exc:
            raise FolderMoveFailed(exc.errno or errno.EIO, f"{source}: {exc}") from exc
    except BaseException:
        if len(changes.moves) > moved_before:
            changes.folders_kept.append(identity)
        raise
    finally:
        for entry in held:
            entry.release()
    changes.folders_removed.append(source)
    return True


def _walk(
    source: Path, dest: Path, changes: Changes, inner: Sequence[_Guard], moved_before: int
) -> bool:
    """Move each child of the folder ``source`` into ``dest`` while ``inner`` holds, as
    :func:`_move_folder` says, and return whether ``source`` may be removed: ``False``
    when it holds only companion files and folders this walk kept."""
    kinds: dict[str, bool] = {}  # each child's name: whether the listing found a folder
    with os.scandir(source) as listing:
        for entry in listing:
            try:
                kinds[entry.name] = entry.is_dir(follow_symlinks=False)
            except OSError:
                kinds[entry.name] = True  # not known to be a file
    kept: set[str] = set()
    for name in sorted(kinds, key=lambda name: claim_key(Path(name))):
        child = source / name
        try:
            _guard(inner)
            try:
                child_st = os.lstat(child)
            except FileNotFoundError:
                if not kinds[name] and is_companion_file(child):
                    continue  # the system removed it with the file it belongs to
                raise
            if is_folder(child, child_st):
                if not _move_folder(child, child_st, dest / name, changes, inner):
                    kept.add(name)
            elif is_companion_file(child):
                kept.add(name)
            else:
                _move_file(child, dest / name, changes, inner)
        except FolderMoveFailed:
            raise
        except NowALink as exc:
            if len(changes.moves) == moved_before:
                raise
            msg = f"{exc.reason}; part of the folder moved"
            raise FolderMoveFailed(errno.ELOOP, msg) from exc
        except OSError as exc:
            raise FolderMoveFailed(exc.errno or errno.EIO, f"{child}: {exc}") from exc
    left = set(os.listdir(source))
    return not (left and left <= kept)


def _move_file(
    source: Path,
    dest: Path,
    changes: Changes,
    guards: Sequence[_Guard],
    expected: PlanFingerprint | None = None,
) -> None:
    """Move a file, a symbolic link or a junction as itself, while ``guards`` hold and,
    with ``expected``, while it is as recorded (:func:`_look`, the last look at the
    source before the rename or hard link)."""
    if os.name == "nt":
        there = _probe(dest)
        _guard(guards)
        st = _look(source, expected)  # the last look before the rename
        if there is not None and os.path.samestat(there, st):
            # The rename would take this name: it is the source's own file.
            msg = "the new name is the source's own file"
            raise FileExistsError(errno.EEXIST, msg, str(dest))
        before = _fingerprint(source, st)
        try:
            os.rename(source, dest)
        except FileExistsError:
            raise
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _LOG.info("Cannot rename %s -> %s (%s); copying instead", source, dest, exc)
            _copy_then_unlink(source, st, dest, before, changes, guards)
            return
        changes.moved(source, dest, before)
        return
    _guard(guards)
    st = _look(source, expected)  # the last look before the hard link
    before = _fingerprint(source, st)
    try:
        os.link(source, dest, follow_symlinks=False)
    except FileExistsError:
        raise
    except (OSError, NotImplementedError) as exc:
        if isinstance(exc, OSError) and exc.errno not in _NO_HARD_LINK:
            raise
        _LOG.info("Cannot hard-link %s -> %s (%s); copying instead", source, dest, exc)
        _copy_then_unlink(source, st, dest, before, changes, guards)
        return
    changes.files_left_behind.append(dest)  # until the source's name is removed
    made = os.lstat(dest)

    def both_names(now: os.stat_result) -> bool:
        # Both names are one file while the new name still holds the file made there,
        # with the links it had then: the old name's removal would have lowered them.
        try:
            at_dest = os.lstat(dest)
        except OSError:
            return False
        return (
            os.path.samestat(at_dest, made)
            and at_dest.st_nlink == made.st_nlink
            and _one_file(now, at_dest)
        )

    _unlink_source(source, dest, made, both_names, both_names, before, changes)


def _unlink_source(
    source: Path,
    dest: Path,
    made: os.stat_result,
    at_old_name: _AtOldName,
    unchanged: _AtOldName,
    before: PlanFingerprint,
    changes: Changes,
    held: _Held | None = None,
) -> None:
    """Remove the source's name now that ``dest`` (``made`` there, listed as left behind)
    holds the file, and record the move.

    The check by name, ``unchanged`` (the source's own file at its old name, as it was
    copied), is the last look before the unlink; on Windows the source ``held`` open is
    released between the two, as Windows removes no file held open. When the old name is
    gone already, the file is at ``dest`` alone and the move is recorded. On any error,
    an interrupt included, :func:`_settle` decides by the disk, with ``at_old_name``, what is
    kept, so the file never loses both names.
    """
    try:
        try:
            now: os.stat_result | None = os.lstat(source)
        except FileNotFoundError:
            now = None
        if now is None:
            _LOG.warning("%s was removed during its move; the file is at %s", source, dest)
        elif not unchanged(now):
            raise OSError(errno.EIO, "the source changed during its move", str(source))
        else:
            if held is not None and os.name == "nt":
                held.release()
            os.unlink(source)
        _forget(changes.files_left_behind, dest)
        changes.moved(source, dest, before)
    except BaseException:
        _settle(source, at_old_name, dest, made, before, changes)
        raise


def _settle(
    source: Path,
    at_old_name: _AtOldName,
    dest: Path,
    made: os.stat_result,
    before: PlanFingerprint,
    changes: Changes,
) -> None:
    """After an error once ``dest`` held the file: remove ``dest`` only while the source's
    own file is verified at its old name (``at_old_name``); record the move when the old name
    is gone; else keep ``dest`` listed as left behind."""
    if any(m.source == source and m.destination == dest for m in changes.moves):
        return  # the move is recorded already
    try:
        now = os.lstat(source)
    except FileNotFoundError:
        _forget(changes.files_left_behind, dest)
        changes.moved(source, dest, before)
        return
    except OSError as exc:
        _LOG.warning("Cannot read %s, so %s is kept: %s", source, dest, exc)
        now = None
    if now is not None and at_old_name(now):
        _remove_if_made(dest, made, changes, source, at_old_name)
    elif dest not in changes.files_left_behind:
        changes.files_left_behind.append(dest)


def _copy_then_unlink(
    source: Path,
    st: os.stat_result,
    dest: Path,
    before: PlanFingerprint,
    changes: Changes,
    guards: Sequence[_Guard],
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
    if stat.S_ISLNK(st.st_mode):
        target = os.readlink(source)
        held = None

        def at_old_name(now: os.stat_result) -> bool:
            # A link is its target text: one with the same text at the old name, made at
            # the same time, leaves nothing lost when the link made at ``dest`` goes.
            try:
                return (
                    _one_file(now, st)
                    and stat.S_ISLNK(now.st_mode)
                    and os.readlink(source) == target
                )
            except OSError:
                return False

        unchanged = at_old_name
    else:
        held = _Held(source, st, folder=False)

        def at_old_name(now: os.stat_result) -> bool:
            return held.agrees(now)

        def unchanged(now: os.stat_result) -> bool:
            # The source's own file, as it was copied.
            return held.agrees(now) and (now.st_size, now.st_mtime_ns) == (
                st.st_size,
                st.st_mtime_ns,
            )

    try:
        if os.name == "nt":
            part = _fresh_name(dest)
            made = _make_copy(source, st, part, changes, guards, at_old_name, held)
            try:
                _guard(guards)
                os.rename(part, dest)
            except BaseException:
                _remove_if_made(part, made, changes, source, at_old_name)
                raise
            changes.files_left_behind.append(dest)
            _forget(changes.files_left_behind, part)
        else:
            made = _make_copy(source, st, dest, changes, guards, at_old_name, held)
        _unlink_source(source, dest, made, at_old_name, unchanged, before, changes, held)
    finally:
        if held is not None:
            held.release()


def _make_copy(
    source: Path,
    st: os.stat_result,
    at: Path,
    changes: Changes,
    guards: Sequence[_Guard],
    at_old_name: _AtOldName,
    held: _Held | None,
) -> os.stat_result:
    """Make a copy of ``source`` (as ``st`` found it, a file ``held`` open) at the new
    name ``at``, while ``guards`` hold, list ``at`` as left behind from the moment it is
    made, and return the copy's stat as made: a link's ``lstat``, or a file's ``fstat``
    once its bytes are written. A copy that fails is removed only while it is the file
    made here and ``at_old_name`` verifies the source at its old name.

    A file's number is read through its descriptor once the copy is complete, and
    again just before a failed copy is removed: on exFAT and FAT32, macOS gives an
    empty file a passing number, which changes when the file is changed, until bytes
    are first written to it."""
    _guard(guards)
    if held is None:  # a link, which is copied as its target text and never opened
        _remake_link(source, st, at, changes)
        made = os.lstat(at)
    else:
        fd = os.open(at, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY, 0o600)
        changes.files_left_behind.append(at)
        try:
            _copy_into(source, st, held, fd)
            made = os.fstat(fd)
        except BaseException:
            _remove_failed_copy(at, fd, changes, source, at_old_name)
            raise
        try:
            os.close(fd)
        except BaseException:
            _remove_if_made(at, made, changes, source, at_old_name)
            raise
        if os.utime not in os.supports_fd:
            _set_times_by_name(at, made, st)
    if not os.path.samestat(os.lstat(at), made):
        raise OSError(errno.EIO, "the copy is not at the name it was made at", str(at))
    return made


def _remove_failed_copy(
    at: Path, fd: int, changes: Changes, source: Path, at_old_name: _AtOldName
) -> None:
    """Close the copy being written through ``fd`` at ``at`` and remove it as
    :func:`_remove_if_made` does, by the number it has now; a copy whose number cannot
    be read stays listed as left behind."""
    try:
        made = os.fstat(fd)
    except OSError as exc:
        _close(fd)
        _LOG.warning("Keeping %s, which Apply made: cannot read it: %s", at, exc)
        return
    _close(fd)
    _remove_if_made(at, made, changes, source, at_old_name)


def _remake_link(source: Path, st: os.stat_result, at: Path, changes: Changes) -> None:
    r"""Make at ``at`` a symbolic link of the kind and with the target text of the link
    ``source`` (``st`` its ``lstat``), so a relative link stays relative, or raise. The
    link is listed as left behind from the moment it is made, and taken off that list
    only when this removes it again.

    On Windows a link is a link to a file or to a folder, and Windows makes a link to a
    folder whenever its target names one, so a link to a file whose target names a
    folder at ``at`` is refused. The ``\\?\`` prefix that :func:`os.readlink` puts
    before an absolute target is left off, as a link made from a plain path has none,
    unless the link made that way does not read back with the same target, such as a
    name ending in a period, which only the prefix keeps.
    """
    target = os.readlink(source)
    if os.name != "nt":
        os.symlink(target, at)
        changes.files_left_behind.append(at)
        return
    folder = _is_folder_link(st)
    if not folder and os.path.isdir(os.path.join(at.parent, target)):
        msg = "a link to a file would be made as a link to a folder at its new place"
        raise OSError(errno.EXDEV, msg, str(source))
    for text in dict.fromkeys((_without_long_path_prefix(target), target)):
        os.symlink(text, at, target_is_directory=folder)
        changes.files_left_behind.append(at)
        made = os.lstat(at)
        if os.readlink(at) == target and _is_folder_link(made) == folder:
            return
        if os.path.samestat(os.lstat(at), made):
            os.unlink(at)
            _forget(changes.files_left_behind, at)
    msg = "the link could not be made again with its kind and target"
    raise OSError(errno.EXDEV, msg, str(source))


def _is_folder_link(st: os.stat_result) -> bool:
    """Whether a Windows link (``st`` its ``lstat``) is a link to a folder."""
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY)


def _without_long_path_prefix(target: str) -> str:
    r"""``\\?\D:\Shows`` as ``D:\Shows`` and ``\\?\UNC\server\share`` as
    ``\\server\share``; any other target as it is."""
    if target.startswith("\\\\?\\UNC\\"):
        return "\\\\" + target[len("\\\\?\\UNC\\") :]
    if target.startswith("\\\\?\\") and target[5:7] == ":\\":
        return target[4:]
    return target


def _fresh_name(dest: Path) -> Path:
    """A name beside ``dest`` that nothing has, for a copy to be made under before it is
    claimed at ``dest``."""
    while True:
        part = dest.with_name(f".termrenamer-{secrets.token_hex(8)}.part")
        if not os.path.lexists(part):
            return part


def _probe(dest: Path) -> os.stat_result | None:
    """``dest``'s ``lstat``, or ``None`` when nothing readable is there: Windows's
    :func:`os.rename` refuses every name that exists but one that is the source's own
    file (another letter case of its name, a separate hard link of it), which the caller
    refuses by this look."""
    try:
        return os.lstat(dest)
    except OSError:
        return None


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError as exc:
        _LOG.warning("Cannot close a file Apply was copying: %s", exc)


def _forget(paths: list[Path], path: Path) -> None:
    if path in paths:
        paths.remove(path)


def _copy_into(source: Path, st: os.stat_result, held: _Held, fd: int) -> None:
    """Write the bytes of ``source`` (as ``st`` found it, ``held`` open) through ``fd``
    and flush them to disk; raise when the source changed during the copy or the sizes
    differ."""
    src = held.descriptor()
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


def _remove_if_made(
    dest: Path, made: os.stat_result, changes: Changes, source: Path, at_old_name: _AtOldName
) -> None:
    """Remove ``dest`` while it still is the entry made here and the source's own file
    is verified at its old name (``at_old_name``), and take it off the files left behind; it
    stays listed when it is kept, so a copy is never removed while it may be the only
    one."""
    try:
        source_there = at_old_name(os.lstat(source))
    except OSError as exc:
        _LOG.warning("Keeping %s, which Apply made: cannot find %s: %s", dest, source, exc)
        return
    if not source_there:
        _LOG.warning("Keeping %s, which Apply made: %s is no longer there", dest, source)
        return
    try:
        if os.path.samestat(os.lstat(dest), made):
            os.unlink(dest)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _LOG.warning("Cannot remove %s, which Apply made: %s", dest, exc)
        return
    _forget(changes.files_left_behind, dest)
