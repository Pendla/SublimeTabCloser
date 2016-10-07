import sublime, sublime_plugin, sys, os
from itertools import chain

# Append the folder that contains all plugins
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

from git import Repo

class GitManager:
    def __init__(self, repo_directory):
        # Construct a repo object from the path that we were given
        self.repo = Repo(repo_directory)

    def get_difference(self):
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
    git_manager = None

    def on_activated_async(self, view):
        if self.git_manager is None:
            project_dir = self.get_project_dir(view)
            self.git_manager = GitManager(project_dir)

        # Get the git difference
        differences = self.git_manager.get_difference()
        for diff in differences:
            for tab in view.window().views():
                print(tab.file_name())
                print(diff.a_path)
                if tab.file_name() is not None and tab.file_name().endswith(diff.a_path):
                    tab.set_scratch(True)
                    tab.close()

    def get_project_dir(self, view):
        return view.window().extract_variables()['folder']
