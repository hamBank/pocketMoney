#!/usr/bin/env bash
# Install this repo's git hooks (fleet spec TST-3). Safe to re-run.
#
#   scripts/install-hooks.sh           # install the pre-push hook
#   scripts/install-hooks.sh --force   # replace a pre-push hook this script didn't install
#
# The installed hook is a two-line stub that runs scripts/pre-push-checks.sh from
# the working tree, so changing the checks never needs a reinstall.
set -Eeuo pipefail

force=0
[ "${1:-}" = "--force" ] && force=1

cd "$(git rev-parse --show-toplevel)"
hooks=$(git rev-parse --git-path hooks)   # honours core.hooksPath and worktrees
mkdir -p "$hooks"
dest="$hooks/pre-push"
marker="# managed by scripts/install-hooks.sh"

if [ -e "$dest" ] && ! grep -qF "$marker" "$dest" && [ "$force" -ne 1 ]; then
    echo "install-hooks: $dest exists and was not installed by this script." >&2
    echo "install-hooks: re-run with --force to replace it." >&2
    exit 1
fi

cat >"$dest" <<EOF
#!/usr/bin/env bash
$marker
exec "\$(git rev-parse --show-toplevel)/scripts/pre-push-checks.sh" "\$@"
EOF
chmod +x "$dest"
echo "installed $dest (skip once with: git push --no-verify)"
