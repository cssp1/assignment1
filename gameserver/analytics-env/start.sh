#!/bin/sh

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR

ENV_FILE=".env"

if [ ! -e "${ENV_FILE}" ]; then
    echo ".env file is missing. Needs to have ENVKEY=... (SpinPunch Management Envkey)"
    exit 1
fi

docker-compose --env-file "${ENV_FILE}" --project-name gameanalytics up --build
