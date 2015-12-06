# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

BUILD_DATE := $(shell date -u)

# Google Closure compiler options

OPTIMIZE := 1 # enable type-based optimization
TYPECHECK := 1 # enable type checking
VARCHECK := 1 # enable checking for missing "var" delcarations

CHECK_FLAGS :=
CHECK_FLAGS += --jscomp_error=accessControls
CHECK_FLAGS += --jscomp_error=visibility
CHECK_FLAGS += --jscomp_warning=globalThis
CHECK_FLAGS += --jscomp_warning=duplicate
CHECK_FLAGS += --jscomp_warning=uselessCode
OPT_FLAGS :=

# note: accessControls/visibility does not work unless checkTypes is also enabled :P

ifneq (${TYPECHECK},)
    CHECK_FLAGS += --jscomp_warning=checkTypes
    CHECK_FLAGS += --jscomp_warning=undefinedNames
    CHECK_FLAGS += --jscomp_warning=undefinedVars
    CHECK_FLAGS += --jscomp_warning=const
    CHECK_FLAGS += --jscomp_warning=constantProperty
    CHECK_FLAGS += --jscomp_warning=invalidCasts
    CHECK_FLAGS += --jscomp_warning=missingProperties
    CHECK_FLAGS += --jscomp_warning=strictModuleDepCheck
    CHECK_FLAGS += --jscomp_warning=suspiciousCode
    CHECK_FLAGS += --jscomp_warning=reportUnknownTypes
else
    CHECK_FLAGS += --jscomp_off=checkTypes
endif

ifneq (${VARCHECK},)
    CHECK_FLAGS += --jscomp_warning=checkVars
else
    CHECK_FLAGS += --jscomp_off=checkVars
endif

ifneq (${OPTIMIZE},)
    OPT_FLAGS += --use_types_for_optimization
endif

.PHONY: clean dep all check

all: dep compiled-client.js
	@true

clean:
	rm -f compiled-client* *.out generated-deps.js

# note: the dependencies are only used when proxyserver is serving the non-obfuscated source code
dep: generated-deps.js

generated-deps.js: clientcode/*.js
	@google/closure/bin/build/depswriter.py --root_with_prefix='clientcode ../../../clientcode' > $@
	@echo "goog.require('SPINPUNCHGAME');" >> $@

compiled-client.js: clientcode/*.js
	@java -client -jar google/compiler.jar \
		--only_closure_dependencies true \
		--closure_entry_point='SPINPUNCHGAME' \
		--language_in=ECMASCRIPT6_STRICT \
		--language_out=ECMASCRIPT5 \
		--externs='externs.js' \
		--js='clientcode' \
		--js='google/closure' \
	        --js='!google/closure/goog/demos/**' \
	        --js='!google/closure/**_test.js' \
		--compilation_level=ADVANCED_OPTIMIZATIONS \
		--summary_detail_level=2 \
		--warning_level=VERBOSE \
		--create_renaming_reports \
		${CHECK_FLAGS} ${OPT_FLAGS} \
		--output_manifest=%outname%_manifest.out \
		--js_output_file=$@ || (rm -f $@ *.out *.date; false) # clean up on failure
	@echo "var gameclient_build_date = \"${BUILD_DATE}\";" >> $@
	@echo "${BUILD_DATE}" > $@.date

check: clientcode/*.js
# OBSOLETE Separate type-checking pass on main.js. Not used anymore, the regular build now uses reportUnknownTypes by default.
# (with @suppress{reportUnknownTypes} to turn off warnings on a file-by-file bases).
# Code kept here in case we want to experiment with other Closure compiler options.

	@google/closure/bin/build/closurebuilder.py \
		--root='google'	--root='clientcode' \
		--namespace='SPINPUNCHGAME' \
		--output_mode=compiled \
		--compiler_jar=google/compiler.jar \
		--compiler_flags='--js=google/closure/goog/deps.js' \
		--compiler_flags='--externs=externs.js' \
		--compiler_flags='--compilation_level=ADVANCED_OPTIMIZATIONS' \
		--compiler_flags='--summary_detail_level=2' \
		--compiler_flags='--warning_level=VERBOSE' \
		--compiler_flags='--language_in=ECMASCRIPT6_STRICT' \
		--compiler_flags='--language_out=ECMASCRIPT5' \
		--output_file=/dev/null \
		${CHECK_FLAGS} ${OPT_FLAGS}

# To find SpinPunch code that is not type-safe yet:
# grep reportUnknownTypes.*XXX clientcode/*.js
