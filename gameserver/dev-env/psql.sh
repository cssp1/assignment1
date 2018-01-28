#!/bin/sh

docker run -it --rm \
--network gametest_default \
-e PGPASSWORD=gametest \
postgres:9.6 \
psql -h pgsql -U gametest
