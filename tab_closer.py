from git import Repo
from itertools import chain
import os

# Get the repo
repo = Repo(os.getcwd())

# Construct the diff that we want to observe.
diff = repo.commit("HEAD@{1}").diff("HEAD")

# Get the deletions from the difference
deletions = diff.iter_change_type('D')

# Get the renames that were performed
renames = diff.iter_change_type('R')

# Now chain the deletions and renames together, so that we can iterate over them
file_changes = chain(deletions, renames)

for change in file_changes:
    print(change)
