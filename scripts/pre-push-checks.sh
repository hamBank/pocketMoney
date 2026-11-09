#!/usr/bin/env bash
# The cheap checks that run before every push (fleet spec TST-3), installed by
# scripts/install-hooks.sh. CI still runs everything (Postgres, migrations,
# conformance, the frontend build); this only catches the quick failures early.
#
#   git push --no-verify          skip the hook once
#   SKIP_PREPUSH=1 git push       same, from the environment
#   PREPUSH_SKIP="pytest" git push    skip named steps: syntax pytest frontend
#
# Not `set -e`: every step runs, so one push shows all the failures.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

if [ "${SKIP_PREPUSH:-}" = 1 ]; then
    echo "pre-push: skipped (SKIP_PREPUSH=1)"
    exit 0
fi

# git feeds "<local ref> <local sha> <remote ref> <remote sha>" lines on stdin.
# A push that only deletes refs (all-zero local sha) has nothing to check.
seen=0
only_deletes=1
if [ ! -t 0 ]; then
    while read -r _ local_sha _ _; do
        seen=1
        [[ $local_sha =~ ^0+$ ]] || only_deletes=0
    done
fi
if [ "$seen" = 1 ] && [ "$only_deletes" = 1 ]; then
    echo "pre-push: only deleting refs, nothing to check"
    exit 0
fi

skip=" ${PREPUSH_SKIP:-} "
failed=()

step() { # step <name> <command...>
    local name=$1
    shift
    case $skip in
    *" $name "*)
        echo "pre-push: skipping $name"
        return
        ;;
    esac
    echo "pre-push: $name"
    "$@" || failed+=("$name")
}

syntax() {
    local rc=0 f
    for f in deploy.sh scripts/*.sh deploy/backup-server/*.sh; do
        [ -f "$f" ] || continue
        bash -n "$f" || rc=1
    done
    return $rc
}

pytest_backend() {
    local py=pytest
    [ -x .venv/bin/pytest ] && py=.venv/bin/pytest
    if ! command -v "$py" >/dev/null 2>&1; then
        echo "  pytest not found: activate your venv (or PREPUSH_SKIP=pytest)"
        return 1
    fi
    "$py" -q -x
}

frontend() {
    if [ ! -d frontend/node_modules ]; then
        echo "  frontend/node_modules missing: run 'npm ci' in frontend/ (lint and tests skipped; CI runs them)"
        return 0
    fi
    (cd frontend && npm run --silent lint && npm test --silent)
}

step syntax syntax
step pytest pytest_backend
step frontend frontend

if [ "${#failed[@]}" -gt 0 ]; then
    echo "pre-push: FAILED: ${failed[*]}"
    echo "  (git push --no-verify skips this; CI still runs everything)"
    exit 1
fi
echo "pre-push: ok"
