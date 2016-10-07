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

