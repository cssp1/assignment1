# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# perform static analysis on our Python code

check: *.py ../gamedata/*.py ../gamedata/*/*.py
# allow any Ctrl-C to exit the loop
	@trap "break 2; exit;" SIGINT; for INPUT in $^; do pyflakes $$INPUT; done
