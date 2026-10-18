#!/usr/bin/env bash
set -euo pipefail

project=${1:?Usage: setup-project.sh /absolute/project/path [web-user]}
web_user=${2:-www-data}
account=$(id -un)
group=$(id -gn)
if [[ "$account" == root || "$project" != /* || "$project" == / ]]; then
  echo 'Run as your own non-root server user and supply the project directory.' >&2
  exit 1
fi

# Retain the current production configuration; never regenerate APP_KEY.
sudo mkdir -p "$project/shared"
if ! sudo test -e "$project/shared/.env"; then
  sudo install -m 640 -o "$account" -g "$web_user" \
    "$project/current/.env" "$project/shared/.env"
fi
if ! sudo test -d "$project/shared/storage"; then
  echo 'Place the existing application storage at shared/storage before continuing.' >&2
  exit 1
fi

sudo mkdir -p "$project/releases" "$project/.release-template/bootstrap/cache"
# Preserve runtime file owners: PHP may need to update their timestamps.
sudo find "$project" -path "$project/shared/storage" -prune -o \
  -exec chown -h "$account:$group" {} +

# Existing code: the account can maintain it; PHP may only read it.
sudo setfacl -R -m "u:$account:rwX,u:$web_user:r-X" "$project"

# New code inherits read-only PHP access, regardless of the SSH session umask.
read_acl="u::rwx,u:$account:rwx,u:$web_user:r-x,g::---,m::rwx,o::---"
for directory in "$project/releases" "$project/.release-template" \
  "$project/.release-template/bootstrap"; do
  sudo setfacl -m "$read_acl" "$directory"
  sudo setfacl -d -m "$read_acl" "$directory"
done

# Runtime paths inherit write access for both the account and PHP.
# The cache template is copied per release; the cache itself is never shared.
for directory in "$project/shared/storage" "$project/.release-template/bootstrap/cache" \
  "$project/current/bootstrap/cache"; do
  sudo setfacl -R -m "u:$account:rwX,u:$web_user:rwX" "$directory"
  sudo setfacl -R -d -m "u::rwx,u:$account:rwx,u:$web_user:rwx,g::---,m::rwx,o::---" "$directory"
done

sudo chown "$account:$web_user" "$project/shared/.env"
sudo chmod 640 "$project/shared/.env"
printf 'Configured %s for SSH user %s and PHP user %s.\n' "$project" "$account" "$web_user"
