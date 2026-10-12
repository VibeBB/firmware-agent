#!/usr/bin/env bash
# Fetch every pinned third-party source archive listed in
# docker/third_party.manifest into its destination directory after a
# sha256 verification. Manifest rows: name|url|sha256|dest
# Rows whose name is prefixed "git:" are fetched as a git commit
# instead of a tarball; the third field is the expected commit SHA and
# the checkout is verified with `git rev-parse HEAD`.
set -euo pipefail

manifest=${1:-/tmp/third_party.manifest}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

while IFS='|' read -r name url sha dest; do
    [[ -z "$name" || "$name" =~ ^# ]] && continue
    if [[ "$name" == git:* ]]; then
        echo "fetch $name @ $sha -> $dest"
        mkdir -p "$dest"
        git init -q "$dest"
        git -C "$dest" remote add origin "$url"
        git -C "$dest" fetch --depth 1 origin "$sha"
        git -C "$dest" -c advice.detachedHead=false checkout -q FETCH_HEAD
        actual=$(git -C "$dest" rev-parse HEAD)
        [[ "$actual" == "$sha" ]] || {
            echo "pin mismatch for $name: expected $sha, got $actual" >&2
            exit 1
        }
        rm -rf "$dest/.git"
        continue
    fi
    archive="$work/$name.tar.gz"
    echo "fetch $name -> $dest"
    curl --fail --location --silent --show-error \
        --retry 5 --retry-delay 10 --retry-all-errors \
        --output "$archive" "$url"
    echo "$sha  $archive" | sha256sum --check >/dev/null
    mkdir -p "$dest"
    tar -xzf "$archive" -C "$dest" --strip-components=1
done < "$manifest"
