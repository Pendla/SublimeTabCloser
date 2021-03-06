import sys, os
# Append the folder that contains all plugins
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

from git import Repo
from itertools import chain

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
