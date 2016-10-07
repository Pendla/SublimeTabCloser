# SublimeTabCloser
Plugin for Sublime Text 3 that closes tabs when they are either renamed or deleted during a git checkout.

## Installation
Clone this repo and place it inside your Packages folder. In OSX this project resides in `~/Library/Application Support/Sublime Text 3/Packages/` _**Plugin will be available in package manager soon**_

## Features
- [x] Close files that were removed or renamed during a git checkout
- [ ] Replace a file that was renamed, instead of simply closing it.
- [ ] Reduce time complexity of the open tabs vs changed files check.
- [ ] Replace git repo for each individual file, instead of taking the git repo of the view which event we received.

## Contributions
I gladly accept pull requests if you have any issues or features that you'd like to include. Please feel free to also create
pull requests for the features above that have not yet been implemented.

## Thanks to
- [@patallen](https://github.com/patallen) for the original idea.
