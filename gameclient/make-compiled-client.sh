#!/bin/sh

OPTIMIZE=1 # enable type-based optimization
TYPECHECK=1 # enable type checking
VARCHECK=1 # enable checking for missing "var" delcarations

# OPTIONS
while getopts "tvo" flag
do
    case $flag in
        o)
            TYPECHECK=1
            VARCHECK=1
            OPTIMIZE=1
            ;;
        t)
            TYPECHECK=1
            VARCHECK=1
            ;;
        v)
            VARCHECK=1
            ;;
    esac
done

CHECK_FLAGS=""
CHECK_FLAGS+=" --compiler_flags=--jscomp_error=accessControls"
CHECK_FLAGS+=" --compiler_flags=--jscomp_error=visibility"
CHECK_FLAGS+=" --compiler_flags=--jscomp_warning=globalThis"
CHECK_FLAGS+=" --compiler_flags=--jscomp_warning=duplicate"
CHECK_FLAGS+=" --compiler_flags=--jscomp_off=uselessCode"
OPT_FLAGS=""

# note: accessControls/visibility does not work unless checkTypes is also enabled :P

if [[ $TYPECHECK == 1 ]]; then
    CHECK_FLAGS+=" --compiler_flags=--jscomp_warning=checkTypes"
#    CHECK_FLAGS+=" --compiler_flags=--jscomp_off=reportUnknownTypes"
    # custom SpinPunch option that shuts up complaints about argument count mismatches
    CHECK_FLAGS+=" --compiler_flags=--jscomp_off=checkTypesArgumentCount"
else
    CHECK_FLAGS+=" --compiler_flags=--jscomp_off=checkTypes"
fi

if [[ $VARCHECK == 1 ]]; then
    CHECK_FLAGS+=" --compiler_flags=--jscomp_warning=checkVars"
else
    CHECK_FLAGS+=" --compiler_flags=--jscomp_off=checkVars"
fi

if [[ $OPTIMIZE == 1 ]]; then
    OPT_FLAGS+=" --compiler_flags=--use_types_for_optimization"
fi

#--compiler_flags='--create_name_map_files' \

BUILD_DATE=`date -u`

google/closure/bin/build/closurebuilder.py \
--root='google' --root='clientcode' \
--namespace='SPINPUNCHGAME' \
--output_mode=compiled --compiler_jar=google/compiler.jar \
--compiler_flags='--js=google/closure/goog/deps.js' \
--compiler_flags='--compilation_level=ADVANCED_OPTIMIZATIONS' \
--compiler_flags='--externs=clientcode/externs.js' \
--compiler_flags='--create_name_map_files' \
${CHECK_FLAGS} ${OPT_FLAGS} \
--output_file=compiled-client.js && \
echo "var gameclient_build_date = \"$BUILD_DATE\";" >> compiled-client.js && \
gzip -9 -c compiled-client.js > compiled-client.js.gz && \
echo "$BUILD_DATE" > compiled-client.js.date && \
mv _props_map.out compiled-client_props_map.out && \
mv _vars_map.out compiled-client_vars_map.out
