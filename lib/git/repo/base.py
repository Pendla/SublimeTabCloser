# repo.py
# Copyright (C) 2008, 2009 Michael Trier (mtrier@gmail.com) and contributors
#
# This module is part of GitPython and is released under
# the BSD License: http://www.opensource.org/licenses/bsd-license.php

from git.exc import (
    InvalidGitRepositoryError,
    NoSuchPathError,
    GitCommandError
)
from git.cmd import (
    Git,
    handle_process_output
)
from git.refs import (
    HEAD,
    Head,
    Reference,
    TagReference,
)
from git.objects import (
    Submodule,
    RootModule,
    Commit
)
from git.util import (
    Actor,
    finalize_process
)
from git.index import IndexFile
from git.config import GitConfigParser
from git.remote import (
    Remote,
    add_progress,
    to_progress_instance
)

from git.db import GitCmdObjectDB

from gitdb.util import (
    join,
    isfile,
    hex_to_bin
)

from .fun import (
    rev_parse,
    is_git_dir,
    find_git_dir,
    touch,
)
from git.compat import (
    text_type,
    defenc,
    PY3,
    safe_decode,
    range,
)

import os
import sys
import re
from collections import namedtuple

DefaultDBType = GitCmdObjectDB
if sys.version_info[:2] < (2, 5):     # python 2.4 compatiblity
    DefaultDBType = GitCmdObjectDB
# END handle python 2.4

BlameEntry = namedtuple('BlameEntry', ['commit', 'linenos', 'orig_path', 'orig_linenos'])


__all__ = ('Repo', )


def _expand_path(p):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(p)))


class Repo(object):
    """Represents a git repository and allows you to query references,
    gather commit information, generate diffs, create and clone repositories query
    the log.

    The following attributes are worth using:

    'working_dir' is the working directory of the git command, which is the working tree
    directory if available or the .git directory in case of bare repositories

    'working_tree_dir' is the working tree directory, but will raise AssertionError
    if we are a bare repository.

    'git_dir' is the .git repository directory, which is always set."""
    DAEMON_EXPORT_FILE = 'git-daemon-export-ok'
    __slots__ = ("working_dir", "_working_tree_dir", "git_dir", "_bare", "git", "odb")

    # precompiled regex
    re_whitespace = re.compile(r'\s+')
    re_hexsha_only = re.compile('^[0-9A-Fa-f]{40}$')
    re_hexsha_shortened = re.compile('^[0-9A-Fa-f]{4,40}$')
    re_author_committer_start = re.compile(r'^(author|committer)')
    re_tab_full_line = re.compile(r'^\t(.*)$')

    # invariants
    # represents the configuration level of a configuration file
    config_level = ("system", "user", "global", "repository")

    # Subclass configuration
    # Subclasses may easily bring in their own custom types by placing a constructor or type here
    GitCommandWrapperType = Git

    def __init__(self, path=None, odbt=DefaultDBType, search_parent_directories=False):
        """Create a new Repo instance

        :param path:
            the path to either the root git directory or the bare git repo::

                repo = Repo("/Users/mtrier/Development/git-python")
                repo = Repo("/Users/mtrier/Development/git-python.git")
                repo = Repo("~/Development/git-python.git")
                repo = Repo("$REPOSITORIES/Development/git-python.git")

        :param odbt:
            Object DataBase type - a type which is constructed by providing
            the directory containing the database objects, i.e. .git/objects. It will
            be used to access all object data
        :param search_parent_directories:
            if True, all parent directories will be searched for a valid repo as well.

            Please note that this was the default behaviour in older versions of GitPython,
            which is considered a bug though.
        :raise InvalidGitRepositoryError:
        :raise NoSuchPathError:
        :return: git.Repo """
        epath = _expand_path(path or os.getcwd())
        self.git = None  # should be set for __del__ not to fail in case we raise
        if not os.path.exists(epath):
            raise NoSuchPathError(epath)

        self.working_dir = None
        self._working_tree_dir = None
        self.git_dir = None
        curpath = epath

        # walk up the path to find the .git dir
        while curpath:
            # ABOUT os.path.NORMPATH
            # It's important to normalize the paths, as submodules will otherwise initialize their
            # repo instances with paths that depend on path-portions that will not exist after being
            # removed. It's just cleaner.
            if is_git_dir(curpath):
                self.git_dir = os.path.normpath(curpath)
                self._working_tree_dir = os.path.dirname(self.git_dir)
                break

            gitpath = find_git_dir(join(curpath, '.git'))
            if gitpath is not None:
                self.git_dir = os.path.normpath(gitpath)
                self._working_tree_dir = curpath
                break

            if not search_parent_directories:
                break
            curpath, dummy = os.path.split(curpath)
            if not dummy:
                break
        # END while curpath

        if self.git_dir is None:
            raise InvalidGitRepositoryError(epath)

        self._bare = False
        try:
            self._bare = self.config_reader("repository").getboolean('core', 'bare')
        except Exception:
            # lets not assume the option exists, although it should
            pass

        # adjust the wd in case we are actually bare - we didn't know that
        # in the first place
        if self._bare:
            self._working_tree_dir = None
        # END working dir handling

        self.working_dir = self._working_tree_dir or self.git_dir
        self.git = self.GitCommandWrapperType(self.working_dir)

        # special handling, in special times
        args = [join(self.git_dir, 'objects')]
        if issubclass(odbt, GitCmdObjectDB):
            args.append(self.git)
        self.odb = odbt(*args)

    def __del__(self):
        if self.git:
            self.git.clear_cache()

    def __eq__(self, rhs):
        if isinstance(rhs, Repo):
            return self.git_dir == rhs.git_dir
        return False

    def __ne__(self, rhs):
        return not self.__eq__(rhs)

    def __hash__(self):
        return hash(self.git_dir)

    # Description property
    def _get_description(self):
        filename = join(self.git_dir, 'description')
        return open(filename, 'rb').read().rstrip().decode(defenc)

    def _set_description(self, descr):
        filename = join(self.git_dir, 'description')
        open(filename, 'wb').write((descr + '\n').encode(defenc))

    description = property(_get_description, _set_description,
                           doc="the project's description")
    del _get_description
    del _set_description

    @property
    def working_tree_dir(self):
        """:return: The working tree directory of our git repository. If this is a bare repository, None is returned.
        """
        return self._working_tree_dir

    @property
    def bare(self):
        """:return: True if the repository is bare"""
        return self._bare

    @property
    def heads(self):
        """A list of ``Head`` objects representing the branch heads in
        this repo

        :return: ``git.IterableList(Head, ...)``"""
        return Head.list_items(self)

    @property
    def references(self):
        """A list of Reference objects representing tags, heads and remote references.

        :return: IterableList(Reference, ...)"""
        return Reference.list_items(self)

    # alias for references
    refs = references

    # alias for heads
    branches = heads

    @property
    def index(self):
        """:return: IndexFile representing this repository's index.
        :note: This property can be expensive, as the returned ``IndexFile`` will be
         reinitialized. It's recommended to re-use the object."""
        return IndexFile(self)

    @property
    def head(self):
        """:return: HEAD Object pointing to the current head reference"""
        return HEAD(self, 'HEAD')

    @property
    def remotes(self):
        """A list of Remote objects allowing to access and manipulate remotes
        :return: ``git.IterableList(Remote, ...)``"""
        return Remote.list_items(self)

    def remote(self, name='origin'):
        """:return: Remote with the specified name
        :raise ValueError:  if no remote with such a name exists"""
        r = Remote(self, name)
        if not r.exists():
            raise ValueError("Remote named '%s' didn't exist" % name)
        return r

    #{ Submodules

    @property
    def submodules(self):
        """
        :return: git.IterableList(Submodule, ...) of direct submodules
            available from the current head"""
        return Submodule.list_items(self)

    def submodule(self, name):
        """ :return: Submodule with the given name
        :raise ValueError: If no such submodule exists"""
        try:
            return self.submodules[name]
        except IndexError:
            raise ValueError("Didn't find submodule named %r" % name)
        # END exception handling

    def create_submodule(self, *args, **kwargs):
        """Create a new submodule

        :note: See the documentation of Submodule.add for a description of the
            applicable parameters
        :return: created submodules"""
        return Submodule.add(self, *args, **kwargs)

    def iter_submodules(self, *args, **kwargs):
        """An iterator yielding Submodule instances, see Traversable interface
        for a description of args and kwargs
        :return: Iterator"""
        return RootModule(self).traverse(*args, **kwargs)

    def submodule_update(self, *args, **kwargs):
        """Update the submodules, keeping the repository consistent as it will
        take the previous state into consideration. For more information, please
        see the documentation of RootModule.update"""
        return RootModule(self).update(*args, **kwargs)

    #}END submodules

    @property
    def tags(self):
        """A list of ``Tag`` objects that are available in this repo
        :return: ``git.IterableList(TagReference, ...)`` """
        return TagReference.list_items(self)

    def tag(self, path):
        """:return: TagReference Object, reference pointing to a Commit or Tag
        :param path: path to the tag reference, i.e. 0.1.5 or tags/0.1.5 """
        return TagReference(self, path)

    def create_head(self, path, commit='HEAD', force=False, logmsg=None):
        """Create a new head within the repository.
        For more documentation, please see the Head.create method.

        :return: newly created Head Reference"""
        return Head.create(self, path, commit, force, logmsg)

    def delete_head(self, *heads, **kwargs):
        """Delete the given heads

        :param kwargs: Additional keyword arguments to be passed to git-branch"""
        return Head.delete(self, *heads, **kwargs)

    def create_tag(self, path, ref='HEAD', message=None, force=False, **kwargs):
        """Create a new tag reference.
        For more documentation, please see the TagReference.create method.

        :return: TagReference object """
        return TagReference.create(self, path, ref, message, force, **kwargs)

    def delete_tag(self, *tags):
        """Delete the given tag references"""
        return TagReference.delete(self, *tags)

    def create_remote(self, name, url, **kwargs):
        """Create a new remote.

        For more information, please see the documentation of the Remote.create
        methods

        :return: Remote reference"""
        return Remote.create(self, name, url, **kwargs)

    def delete_remote(self, remote):
        """Delete the given remote."""
        return Remote.remove(self, remote)

    def _get_config_path(self, config_level):
        # we do not support an absolute path of the gitconfig on windows ,
        # use the global config instead
        if sys.platform == "win32" and config_level == "system":
            config_level = "global"

        if config_level == "system":
            return "/etc/gitconfig"
        elif config_level == "user":
            config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.environ.get("HOME", '~'), ".config")
            return os.path.normpath(os.path.expanduser(join(config_home, "git", "config")))
        elif config_level == "global":
            return os.path.normpath(os.path.expanduser("~/.gitconfig"))
        elif config_level == "repository":
            return os.path.normpath(join(self.git_dir, "config"))

        raise ValueError("Invalid configuration level: %r" % config_level)

    def config_reader(self, config_level=None):
        """
        :return:
            GitConfigParser allowing to read the full git configuration, but not to write it

            The configuration will include values from the system, user and repository
            configuration files.

        :param config_level:
            For possible values, see config_writer method
            If None, all applicable levels will be used. Specify a level in case
            you know which exact file you whish to read to prevent reading multiple files for
            instance
        :note: On windows, system configuration cannot currently be read as the path is
            unknown, instead the global path will be used."""
        files = None
        if config_level is None:
            files = [self._get_config_path(f) for f in self.config_level]
        else:
            files = [self._get_config_path(config_level)]
        return GitConfigParser(files, read_only=True)

    def config_writer(self, config_level="repository"):
        """
        :return:
            GitConfigParser allowing to write values of the specified configuration file level.
            Config writers should be retrieved, used to change the configuration, and written
            right away as they will lock the configuration file in question and prevent other's
            to write it.

        :param config_level:
            One of the following values
            system = sytem wide configuration file
            global = user level configuration file
            repository = configuration file for this repostory only"""
        return GitConfigParser(self._get_config_path(config_level), read_only=False)

    def commit(self, rev=None):
        """The Commit object for the specified revision
        :param rev: revision specifier, see git-rev-parse for viable options.
        :return: ``git.Commit``"""
        if rev is None:
            return self.head.commit
        else:
            return self.rev_parse(text_type(rev) + "^0")

    def iter_trees(self, *args, **kwargs):
        """:return: Iterator yielding Tree objects
        :note: Takes all arguments known to iter_commits method"""
        return (c.tree for c in self.iter_commits(*args, **kwargs))

    def tree(self, rev=None):
        """The Tree object for the given treeish revision
        Examples::

              repo.tree(repo.heads[0])

        :param rev: is a revision pointing to a Treeish ( being a commit or tree )
        :return: ``git.Tree``

        :note:
            If you need a non-root level tree, find it by iterating the root tree. Otherwise
            it cannot know about its path relative to the repository root and subsequent
            operations might have unexpected results."""
        if rev is None:
            return self.head.commit.tree
        else:
            return self.rev_parse(text_type(rev) + "^{tree}")

    def iter_commits(self, rev=None, paths='', **kwargs):
        """A list of Commit objects representing the history of a given ref/commit

        :parm rev:
            revision specifier, see git-rev-parse for viable options.
            If None, the active branch will be used.

        :parm paths:
            is an optional path or a list of paths to limit the returned commits to
            Commits that do not contain that path or the paths will not be returned.

        :parm kwargs:
            Arguments to be passed to git-rev-list - common ones are
            max_count and skip

        :note: to receive only commits between two named revisions, use the
            "revA...revB" revision specifier

        :return ``git.Commit[]``"""
        if rev is None:
            rev = self.head.commit

        return Commit.iter_items(self, rev, paths, **kwargs)

    def merge_base(self, *rev, **kwargs):
        """Find the closest common ancestor for the given revision (e.g. Commits, Tags, References, etc)

        :param rev: At least two revs to find the common ancestor for.
        :param kwargs: Additional arguments to be passed to the repo.git.merge_base() command which does all the work.
        :return: A list of Commit objects. If --all was not specified as kwarg, the list will have at max one Commit,
            or is empty if no common merge base exists.
        :raises ValueError: If not at least two revs are provided
        """
        if len(rev) < 2:
            raise ValueError("Please specify at least two revs, got only %i" % len(rev))
        # end handle input

        res = list()
        try:
            lines = self.git.merge_base(*rev, **kwargs).splitlines()
        except GitCommandError as err:
            if err.status == 128:
                raise
            # end handle invalid rev
            # Status code 1 is returned if there is no merge-base
            # (see https://github.com/git/git/blob/master/builtin/merge-base.c#L16)
            return res
        # end exception handling

        for line in lines:
            res.append(self.commit(line))
        # end for each merge-base

        return res

    def is_ancestor(self, ancestor_rev, rev):
        """Check if a commit  is an ancestor of another

        :param ancestor_rev: Rev which should be an ancestor
        :param rev: Rev to test against ancestor_rev
        :return: ``True``, ancestor_rev is an accestor to rev.
        """
        try:
            self.git.merge_base(ancestor_rev, rev, is_ancestor=True)
        except GitCommandError as err:
            if err.status == 1:
                return False
            raise
        return True

    def _get_daemon_export(self):
        filename = join(self.git_dir, self.DAEMON_EXPORT_FILE)
        return os.path.exists(filename)

    def _set_daemon_export(self, value):
        filename = join(self.git_dir, self.DAEMON_EXPORT_FILE)
        fileexists = os.path.exists(filename)
        if value and not fileexists:
            touch(filename)
        elif not value and fileexists:
            os.unlink(filename)

    daemon_export = property(_get_daemon_export, _set_daemon_export,
                             doc="If True, git-daemon may export this repository")
    del _get_daemon_export
    del _set_daemon_export

    def _get_alternates(self):
        """The list of alternates for this repo from which objects can be retrieved

        :return: list of strings being pathnames of alternates"""
        alternates_path = join(self.git_dir, 'objects', 'info', 'alternates')

        if os.path.exists(alternates_path):
            try:
                f = open(alternates_path, 'rb')
                alts = f.read().decode(defenc)
            finally:
                f.close()
            return alts.strip().splitlines()
        else:
            return list()

    def _set_alternates(self, alts):
        """Sets the alternates

        :parm alts:
            is the array of string paths representing the alternates at which
            git should look for objects, i.e. /home/user/repo/.git/objects

        :raise NoSuchPathError:
        :note:
            The method does not check for the existance of the paths in alts
            as the caller is responsible."""
        alternates_path = join(self.git_dir, 'objects', 'info', 'alternates')
        if not alts:
            if isfile(alternates_path):
                os.remove(alternates_path)
        else:
            try:
                f = open(alternates_path, 'wb')
                f.write("\n".join(alts).encode(defenc))
            finally:
                f.close()
            # END file handling
        # END alts handling

    alternates = property(_get_alternates, _set_alternates,
                          doc="Retrieve a list of alternates paths or set a list paths to be used as alternates")

    def is_dirty(self, index=True, working_tree=True, untracked_files=False,
                 submodules=True, path=None):
        """
        :return:
            ``True``, the repository is considered dirty. By default it will react
            like a git-status without untracked files, hence it is dirty if the
            index or the working copy have changes."""
        if self._bare:
            # Bare repositories with no associated working directory are
            # always consired to be clean.
            return False

        # start from the one which is fastest to evaluate
        default_args = ['--abbrev=40', '--full-index', '--raw']
        if not submodules:
            default_args.append('--ignore-submodules')
        if path:
            default_args.append(path)
        if index:
            # diff index against HEAD
            if isfile(self.index.path) and \
                    len(self.git.diff('--cached', *default_args)):
                return True
        # END index handling
        if working_tree:
            # diff index against working tree
            if len(self.git.diff(*default_args)):
                return True
        # END working tree handling
        if untracked_files:
            if len(self._get_untracked_files(path, ignore_submodules=not submodules)):
                return True
        # END untracked files
        return False

    @property
    def untracked_files(self):
        """
        :return:
            list(str,...)

            Files currently untracked as they have not been staged yet. Paths
            are relative to the current working directory of the git command.

        :note:
            ignored files will not appear here, i.e. files mentioned in .gitignore
        :note:
            This property is expensive, as no cache is involved. To process the result, please
            consider caching it yourself."""
        return self._get_untracked_files()

    def _get_untracked_files(self, *args, **kwargs):
        # make sure we get all files, no only untracked directores
        proc = self.git.status(*args,
                               porcelain=True,
                               untracked_files=True,
                               as_process=True,
                               **kwargs)
        # Untracked files preffix in porcelain mode
        prefix = "?? "
        untracked_files = list()
        for line in proc.stdout:
            line = line.decode(defenc)
            if not line.startswith(prefix):
                continue
            filename = line[len(prefix):].rstrip('\n')
            # Special characters are escaped
            if filename[0] == filename[-1] == '"':
                filename = filename[1:-1]
                if PY3:
                    # WHATEVER ... it's a mess, but works for me
                    filename = filename.encode('ascii').decode('unicode_escape').encode('latin1').decode(defenc)
                else:
                    filename = filename.decode('string_escape').decode(defenc)
            untracked_files.append(filename)
        finalize_process(proc)
        return untracked_files

    @property
    def active_branch(self):
        """The name of the currently active branch.

        :return: Head to the active branch"""
        return self.head.reference

    def blame_incremental(self, rev, file, **kwargs):
        """Iterator for blame information for the given file at the given revision.

        Unlike .blame(), this does not return the actual file's contents, only
        a stream of BlameEntry tuples.

        :parm rev: revision specifier, see git-rev-parse for viable options.
        :return: lazy iterator of BlameEntry tuples, where the commit
                 indicates the commit to blame for the line, and range
                 indicates a span of line numbers in the resulting file.

        If you combine all line number ranges outputted by this command, you
        should get a continuous range spanning all line numbers in the file.
        """
        data = self.git.blame(rev, '--', file, p=True, incremental=True, stdout_as_string=False, **kwargs)
        commits = dict()

        stream = (line for line in data.split(b'\n') if line)
        while True:
            line = next(stream)  # when exhausted, casues a StopIteration, terminating this function
            hexsha, orig_lineno, lineno, num_lines = line.split()
            lineno = int(lineno)
            num_lines = int(num_lines)
            orig_lineno = int(orig_lineno)
            if hexsha not in commits:
                # Now read the next few lines and build up a dict of properties
                # for this commit
                props = dict()
                while True:
                    line = next(stream)
                    if line == b'boundary':
                        # "boundary" indicates a root commit and occurs
                        # instead of the "previous" tag
                        continue

                    tag, value = line.split(b' ', 1)
                    props[tag] = value
                    if tag == b'filename':
                        # "filename" formally terminates the entry for --incremental
                        orig_filename = value
                        break

                c = Commit(self, hex_to_bin(hexsha),
                           author=Actor(safe_decode(props[b'author']),
                                        safe_decode(props[b'author-mail'].lstrip(b'<').rstrip(b'>'))),
                           authored_date=int(props[b'author-time']),
                           committer=Actor(safe_decode(props[b'committer']),
                                           safe_decode(props[b'committer-mail'].lstrip(b'<').rstrip(b'>'))),
                           committed_date=int(props[b'committer-time']))
                commits[hexsha] = c
            else:
                # Discard the next line (it's a filename end tag)
                line = next(stream)
                tag, value = line.split(b' ', 1)
                assert tag == b'filename', 'Unexpected git blame output'
                orig_filename = value

            yield BlameEntry(commits[hexsha],
                             range(lineno, lineno + num_lines),
                             safe_decode(orig_filename),
                             range(orig_lineno, orig_lineno + num_lines))

    def blame(self, rev, file, incremental=False, **kwargs):
        """The blame information for the given file at the given revision.

        :parm rev: revision specifier, see git-rev-parse for viable options.
        :return:
            list: [git.Commit, list: [<line>]]
            A list of tuples associating a Commit object with a list of lines that
            changed within the given commit. The Commit objects will be given in order
            of appearance."""
        if incremental:
            return self.blame_incremental(rev, file, **kwargs)

        data = self.git.blame(rev, '--', file, p=True, stdout_as_string=False, **kwargs)
        commits = dict()
        blames = list()
        info = None

        keepends = True
        for line in data.splitlines(keepends):
            try:
                line = line.rstrip().decode(defenc)
            except UnicodeDecodeError:
                firstpart = ''
                is_binary = True
            else:
                # As we don't have an idea when the binary data ends, as it could contain multiple newlines
                # in the process. So we rely on being able to decode to tell us what is is.
                # This can absolutely fail even on text files, but even if it does, we should be fine treating it
                # as binary instead
                parts = self.re_whitespace.split(line, 1)
                firstpart = parts[0]
                is_binary = False
            # end handle decode of line

            if self.re_hexsha_only.search(firstpart):
                # handles
                # 634396b2f541a9f2d58b00be1a07f0c358b999b3 1 1 7        - indicates blame-data start
                # 634396b2f541a9f2d58b00be1a07f0c358b999b3 2 2          - indicates
                # another line of blame with the same data
                digits = parts[-1].split(" ")
                if len(digits) == 3:
                    info = {'id': firstpart}
                    blames.append([None, []])
                elif info['id'] != firstpart:
                    info = {'id': firstpart}
                    blames.append([commits.get(firstpart), []])
                # END blame data initialization
            else:
                m = self.re_author_committer_start.search(firstpart)
                if m:
                    # handles:
                    # author Tom Preston-Werner
                    # author-mail <tom@mojombo.com>
                    # author-time 1192271832
                    # author-tz -0700
                    # committer Tom Preston-Werner
                    # committer-mail <tom@mojombo.com>
                    # committer-time 1192271832
                    # committer-tz -0700  - IGNORED BY US
                    role = m.group(0)
                    if firstpart.endswith('-mail'):
                        info["%s_email" % role] = parts[-1]
                    elif firstpart.endswith('-time'):
                        info["%s_date" % role] = int(parts[-1])
                    elif role == firstpart:
                        info[role] = parts[-1]
                    # END distinguish mail,time,name
                else:
                    # handle
                    # filename lib/grit.rb
                    # summary add Blob
                    # <and rest>
                    if firstpart.startswith('filename'):
                        info['filename'] = parts[-1]
                    elif firstpart.startswith('summary'):
                        info['summary'] = parts[-1]
                    elif firstpart == '':
                        if info:
                            sha = info['id']
                            c = commits.get(sha)
                            if c is None:
                                c = Commit(self, hex_to_bin(sha),
                                           author=Actor._from_string(info['author'] + ' ' + info['author_email']),
                                           authored_date=info['author_date'],
                                           committer=Actor._from_string(
                                               info['committer'] + ' ' + info['committer_email']),
                                           committed_date=info['committer_date'])
                                commits[sha] = c
                            # END if commit objects needs initial creation
                            if not is_binary:
                                if line and line[0] == '\t':
                                    line = line[1:]
                            else:
                                # NOTE: We are actually parsing lines out of binary data, which can lead to the
                                # binary being split up along the newline separator. We will append this to the blame
                                # we are currently looking at, even though it should be concatenated with the last line
                                # we have seen.
                                pass
                            # end handle line contents
                            blames[-1][0] = c
                            blames[-1][1].append(line)
                            info = {'id': sha}
                        # END if we collected commit info
                    # END distinguish filename,summary,rest
                # END distinguish author|committer vs filename,summary,rest
            # END distinguish hexsha vs other information
        return blames

    @classmethod
    def init(cls, path=None, mkdir=True, odbt=DefaultDBType, **kwargs):
        """Initialize a git repository at the given path if specified

        :param path:
            is the full path to the repo (traditionally ends with /<name>.git)
            or None in which case the repository will be created in the current
            working directory

        :parm mkdir:
            if specified will create the repository directory if it doesn't
            already exists. Creates the directory with a mode=0755.
            Only effective if a path is explicitly given

        :param odbt:
            Object DataBase type - a type which is constructed by providing
            the directory containing the database objects, i.e. .git/objects.
            It will be used to access all object data

        :parm kwargs:
            keyword arguments serving as additional options to the git-init command

        :return: ``git.Repo`` (the newly created repo)"""
        if path:
            path = _expand_path(path)
        if mkdir and path and not os.path.exists(path):
            os.makedirs(path, 0o755)

        # git command automatically chdir into the directory
        git = Git(path)
        git.init(**kwargs)
        return cls(path, odbt=odbt)

    @classmethod
    def _clone(cls, git, url, path, odb_default_type, progress, **kwargs):
        if progress is not None:
            progress = to_progress_instance(progress)

        # special handling for windows for path at which the clone should be
        # created.
        # tilde '~' will be expanded to the HOME no matter where the ~ occours. Hence
        # we at least give a proper error instead of letting git fail
        prev_cwd = None
        prev_path = None
        odbt = kwargs.pop('odbt', odb_default_type)
        if os.name == 'nt':
            if '~' in path:
                raise OSError("Git cannot handle the ~ character in path %r correctly" % path)

            # on windows, git will think paths like c: are relative and prepend the
            # current working dir ( before it fails ). We temporarily adjust the working
            # dir to make this actually work
            match = re.match("(\w:[/\\\])(.*)", path)
            if match:
                prev_cwd = os.getcwd()
                prev_path = path
                drive, rest_of_path = match.groups()
                os.chdir(drive)
                path = rest_of_path
                kwargs['with_keep_cwd'] = True
            # END cwd preparation
        # END windows handling

        try:
            proc = git.clone(url, path, with_extended_output=True, as_process=True,
                             v=True, **add_progress(kwargs, git, progress))
            if progress:
                handle_process_output(proc, None, progress.new_message_handler(), finalize_process)
            else:
                (stdout, stderr) = proc.communicate()
                finalize_process(proc, stderr=stderr)
            # end handle progress
        finally:
            if prev_cwd is not None:
                os.chdir(prev_cwd)
                path = prev_path
            # END reset previous working dir
        # END bad windows handling

        # our git command could have a different working dir than our actual
        # environment, hence we prepend its working dir if required
        if not os.path.isabs(path) and git.working_dir:
            path = join(git._working_dir, path)

        # adjust remotes - there may be operating systems which use backslashes,
        # These might be given as initial paths, but when handling the config file
        # that contains the remote from which we were clones, git stops liking it
        # as it will escape the backslashes. Hence we undo the escaping just to be
        # sure
        repo = cls(os.path.abspath(path), odbt=odbt)
        if repo.remotes:
            writer = repo.remotes[0].config_writer
            writer.set_value('url', repo.remotes[0].url.replace("\\\\", "\\").replace("\\", "/"))
            # PY3: be sure cleanup is performed and lock is released
            writer.release()
        # END handle remote repo
        return repo

    def clone(self, path, progress=None, **kwargs):
        """Create a clone from this repository.

        :param path: is the full path of the new repo (traditionally ends with ./<name>.git).
        :param progress: See 'git.remote.Remote.push'.
        :param kwargs:
            * odbt = ObjectDatabase Type, allowing to determine the object database
              implementation used by the returned Repo instance
            * All remaining keyword arguments are given to the git-clone command

        :return: ``git.Repo`` (the newly cloned repo)"""
        return self._clone(self.git, self.git_dir, path, type(self.odb), progress, **kwargs)

    @classmethod
    def clone_from(cls, url, to_path, progress=None, env=None, **kwargs):
        """Create a clone from the given URL

        :param url: valid git url, see http://www.kernel.org/pub/software/scm/git/docs/git-clone.html#URLS
        :param to_path: Path to which the repository should be cloned to
        :param progress: See 'git.remote.Remote.push'.
        :param env: Optional dictionary containing the desired environment variables.
        :param kwargs: see the ``clone`` method
        :return: Repo instance pointing to the cloned directory"""
        git = Git(os.getcwd())
        if env is not None:
            git.update_environment(**env)
        return cls._clone(git, url, to_path, GitCmdObjectDB, progress, **kwargs)

    def archive(self, ostream, treeish=None, prefix=None, **kwargs):
        """Archive the tree at the given revision.

        :parm ostream: file compatible stream object to which the archive will be written as bytes
        :parm treeish: is the treeish name/id, defaults to active branch
        :parm prefix: is the optional prefix to prepend to each filename in the archive
        :parm kwargs: Additional arguments passed to git-archive

            * Use the 'format' argument to define the kind of format. Use
              specialized ostreams to write any format supported by python.
            * You may specify the special **path** keyword, which may either be a repository-relative
              path to a directory or file to place into the archive, or a list or tuple of multipe paths.

        :raise GitCommandError: in case something went wrong
        :return: self"""
        if treeish is None:
            treeish = self.head.commit
        if prefix and 'prefix' not in kwargs:
            kwargs['prefix'] = prefix
        kwargs['output_stream'] = ostream
        path = kwargs.pop('path', list())
        if not isinstance(path, (tuple, list)):
            path = [path]
        # end assure paths is list

        self.git.archive(treeish, *path, **kwargs)
        return self

    def has_separate_working_tree(self):
        """
        :return: True if our git_dir is not at the root of our working_tree_dir, but a .git file with a
            platform agnositic symbolic link. Our git_dir will be whereever the .git file points to
        :note: bare repositories will always return False here
        """
        if self.bare:
            return False
        return os.path.isfile(os.path.join(self.working_tree_dir, '.git'))

    rev_parse = rev_parse

    def __repr__(self):
        return '<git.Repo "%s">' % self.git_dir