import sublime, sublime_plugin, sys, os
from itertools import chain

# Append the folder that contains all plugins
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

from git import Repo

class GitManager:
    """
    Implements every github command that needs to be used in order to determine
    which files have been changed.
    """

    def __init__(self, repo_directory):
        # Construct a repo object from the path that we were given
        self.repo = Repo(repo_directory)

    def get_difference(self):
        """
        Get the difference between the current commit and the commit that
        we were previously at. Return any files (names) if they have either
        been renamed or deleted.
        """

        # Construct the diff that we want to observe
        diff = self.repo.commit("HEAD@{1}").diff("HEAD")

        # Get the files that were deleted
        deleted = diff.iter_change_type('D')

        # Get the files that were renamed
        renamed = diff.iter_change_type('R')

        # Now chain the deleted and renamed files together into a new generator
        # and return
        return chain(deleted, renamed)

class TabCloserEventListener(sublime_plugin.EventListener):
    """
    Listens to events from SublimeText. Used to perform the relevant operations
    at the correct times, which causes the program to operate in general.
    """
    git_manager = None

    def on_activated_async(self, view):
        """
        Fires every time a new tab is selected.
        Compares every open tab, and checks if git has marked that file as
        a renamed or deleted file. If so, it closes that tab.

        Keyword arguments:
        view -- The view that was activated
        """

        # If the git manager has not previsouly been defined, create it.
        if self.git_manager is None:
            project_dir = self.get_project_dir(view)
            self.git_manager = GitManager(project_dir)

        # Get the git difference
        differences = self.git_manager.get_difference()

        # TODO  Try to reduce the complexity of this. Should be possible to do
        #       in O(n) by storing file names in a dictionary.
        for diff in differences:
            for tab in view.window().views():
                if tab.file_name() is not None and tab.file_name().endswith(diff.a_path):
                    tab.set_scratch(True)
                    tab.close()

    def get_project_dir(self, view):
        """
        Get the working directory of the given view.

        Keyword arguments:
        view -- The view, which buffer you want to determine the folder of
        """
        return view.window().extract_variables()['folder']
