#!/bin/sh

set -e

auto_confirm=0

confirm () {
    if [ "$auto_confirm" = "1" ]; then
        return 0
    fi

    printf "Are you sure you want to proceed? (y/N) "
    read -r REPLY
    case "$REPLY" in
        [Yy])
            ;;
        *)
            echo "Script canceled."
            exit 1
            ;;
    esac
}

if [ "$1" = "-y" ]; then
    auto_confirm=1
fi

echo ""
echo "*** WARNING: This will remove all containers and container data, and optionally reset .env ***"
echo ""

confirm

echo "===> Stopping and removing all containers..."

if [ -f ".env" ]; then
    docker compose -f docker-compose.yml -f ./dev/docker-compose.dev.yml down -v --remove-orphans
elif [ -f "config.env.template" ]; then
    echo "No .env found, using config.env.template for docker compose down..."
    docker compose --env-file config.env.template -f docker-compose.yml -f ./dev/docker-compose.dev.yml down -v --remove-orphans
else
    echo "Skipping 'docker compose down' because there's no env-file."
fi

echo "===> Cleaning up bind-mounted directories..."
BIND_MOUNTS="./volumes/db/data ./volumes/storage"

for dir in $BIND_MOUNTS; do
    if [ -d "$dir" ]; then
        echo "Removing $dir..."
        confirm
        rm -rf "$dir"
    else
        echo "$dir not found."
    fi
done

echo "===> Resetting .env file (will save backup to .env.old)..."
confirm
if [ -f ".env" ] || [ -L ".env" ]; then
    echo "Renaming existing .env file to .env.old"
    mv .env .env.old
else
    echo "No .env file found."
fi

if [ -f "config.env.template" ]; then
    echo "===> Copying config.env.template to .env"
    cp config.env.template .env
else
    echo "No config.env.template found, can't restore .env to default values."
fi

echo "Cleanup complete!"
echo "Re-run 'docker compose pull' to update images."
echo ""
