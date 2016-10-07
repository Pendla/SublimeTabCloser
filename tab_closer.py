import sublime, sublime_plugin, sys, os
from itertools import chain

# Append the folder that contains all plugins
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

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
