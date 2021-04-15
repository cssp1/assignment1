# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# perform static analysis on our Python code
GAMESERVER_PYSOURCES := *.py ChatMom/*.py
GAMEDATA_PYSOURCES := ../gamedata/*.py
PARALLEL := 4
FLAKE8?=flake8

check_gameserver: ${GAMESERVER_PYSOURCES}
	@echo "Running flake8 on gameserver Python sources..."
	@trap "break 2; exit;" INT
	@${FLAKE8} $^

pylint: ${GAMESERVER_PYSOURCES} ${GAMEDATA_PYSOURCES}
	pylint -j ${PARALLEL} $^

# check Cyclomatic Complexity using the "radon" python module
radon: ${GAMESERVER_PYSOURCES} ${GAMEDATA_PYSOURCES}
	@trap "break 2; exit;" SIGINT; for INPUT in $^; do radon cc $$INPUT -nd; done
