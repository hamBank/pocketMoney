#!/usr/bin/env bash
# Fleet spec PRC-2: give a fresh remote Claude Code session what it needs to run
# both test suites. Does nothing on a local machine, where you manage your own venv.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

cd "$CLAUDE_PROJECT_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
(cd frontend && npm ci --silent)

# Local tooling (alembic, scripts, uvicorn) refuses the default JWT_SECRET with
# auth on (CFG-2); tests set their own. Put the venv first on PATH too.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export AUTH_ENABLED=false' >> "$CLAUDE_ENV_FILE"
    echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
