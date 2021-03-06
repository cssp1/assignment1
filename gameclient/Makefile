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
CHECK_FLAGS += --jscomp_warning=deprecated
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

# For debugging Closure compiler module renaming, it may be helpful to disable unused-file pruning
# by removing the --dependency_mode and --entry_point flags. This will caused Closure to try to compile
# *everything* in the library together (including test cases and experimental code that would never
# be reached by any user of the library). The compilation process will finish but you will get a broken
# compiled executable (still useful to check the manifest and renaming reports though).
# In order to facilitate this, manually prune away most of the irrelevant code from the Closure library.
CLOSURE_LIB_FILES:= --js='google/third_party/closure/goog/mochikit/async/*.js' \
 --js='google/closure/**.js' \
 --js='!google/closure/test_module*.js' \
 --js='!google/closure/**_test*.js' \
 --js='!google/closure/**_perf.js' \
 --js='!google/closure/**tester.js' \
 --js='!google/closure/goog/bootstrap/**' \
 --js='!google/closure/goog/cssom/**' \
 --js='!google/closure/goog/debug/divconsole.js' \
 --js='!google/closure/goog/debug/devcss/**' \
 --js='!google/closure/goog/debug/fpsdisplay.js' \
 --js='!google/closure/goog/demos/**' \
 --js='!google/closure/goog/editor/**' \
 --js='!google/closure/goog/events/*tester.js' \
 --js='!google/closure/goog/fx/**' \
 --js='!google/closure/goog/gears/**' \
 --js='!google/closure/goog/graphics/**' \
 --js='!google/closure/goog/labs/testing/**' \
 --js='!google/closure/goog/labs/pubsub/**' \
 --js='!google/closure/goog/labs/storage/**' \
 --js='!google/closure/goog/module/testdata/**' \
 --js='!google/closure/goog/positioning/**' \
 --js='!google/closure/goog/promise/testsuiteadapter.js' \
 --js='!google/closure/goog/storage/**' \
 --js='!google/closure/goog/testing/**' \
 --js='!google/closure/goog/tweak/**' \
 --js='!google/closure/goog/ui/**'

compiled-client.js: clientcode/*.js
	@java -client -jar google/compiler.jar \
		--language_in=ECMASCRIPT6_STRICT \
		--language_out=ECMASCRIPT5 \
		--dependency_mode=STRICT \
		--entry_point='goog:SPINPUNCHGAME' \
		--process_common_js_modules \
		--externs='externs.js' \
		--js='clientcode/*.js' \
		${CLOSURE_LIB_FILES} \
		--js='pako/index.js' \
		--js='pako/lib/**.js' \
		--compilation_level=ADVANCED \
		--summary_detail_level=2 \
		--warning_level=VERBOSE \
		--create_renaming_reports \
		${CHECK_FLAGS} ${OPT_FLAGS} \
		--output_manifest=%outname%_manifest.out \
		--js_output_file=$@ \
		|| (rm -f $@ *.out *.date; false) # clean up on failure
	@echo "var gameclient_build_date = \"${BUILD_DATE}\";" >> $@
	@echo "${BUILD_DATE}" > $@.date

# variant of the build with experimental Closure compiler checks
check: clientcode/*.js
	@java -client -jar google/compiler.jar \
		--language_in=ECMASCRIPT6_STRICT \
		--language_out=ECMASCRIPT5 \
		--dependency_mode=STRICT \
		--entry_point='goog:SPINPUNCHGAME' \
		--process_common_js_modules \
		--externs='externs.js' \
		--js='clientcode/*.js' \
		${CLOSURE_LIB_FILES} \
		--js='pako/index.js' \
		--js='pako/lib/**.js' \
		--compilation_level=ADVANCED \
		--summary_detail_level=2 \
		--warning_level=VERBOSE \
		${CHECK_FLAGS} ${OPT_FLAGS} \
		--js_output_file=/dev/null 2>&1 \
		| tee /dev/stderr | grep -q '0 error(s), 0 warning(s)'

# note: the tee | grep pattern above causes the java command to emit a nonzero exit code
# when its output does NOT include "0 error(s), 0 warning(s)". tee is used to echo the
# compiler's stdout+stderr to the console-visible output while also sending it along the pipe to grep.

# To find SpinPunch code that is not type-safe yet:
# grep reportUnknownTypes.*XXX clientcode/*.js
