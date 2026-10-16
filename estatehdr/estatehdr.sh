#!/usr/bin/env bash
# EstateHDR - uruchamianie jedną komendą.
#   ./estatehdr.sh process <folder> [opcje]   obróbka folderu (serie bracketingowe / pojedyncze zdjęcia)
#   ./estatehdr.sh web [--port 8765]           lokalny interfejs webowy (http://127.0.0.1:8765)
#   ./estatehdr.sh test                        testy automatyczne
#   ./estatehdr.sh presets | group <folder>
# Przy pierwszym uruchomieniu tworzy .venv i instaluje requirements.txt (ponownie tylko po jego zmianie).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${ESTATEHDR_VENV:-$HERE/.venv}"
PY="${PYTHON:-python3}"
if [ ! -x "$VENV/bin/python" ]; then
  echo "[EstateHDR] tworzę środowisko Pythona w $VENV ..." >&2
  "$PY" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip >&2
fi
STAMP="$VENV/.requirements.sha1"
SUM="$("$VENV/bin/python" -c 'import hashlib,sys;print(hashlib.sha1(open(sys.argv[1],"rb").read()).hexdigest())' "$HERE/requirements.txt")"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$SUM" ]; then
  echo "[EstateHDR] instaluję zależności (requirements.txt) ..." >&2
  "$VENV/bin/python" -m pip install -q -r "$HERE/requirements.txt" >&2
  echo "$SUM" > "$STAMP"
fi
export PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
cmd="${1:-help}"
[ $# -gt 0 ] && shift
case "$cmd" in
  test) cd "$HERE" && exec "$VENV/bin/python" -m pytest -q tests "$@" ;;
  help|-h|--help) exec "$VENV/bin/python" -m estatehdr --help ;;
  *) exec "$VENV/bin/python" -m estatehdr "$cmd" "$@" ;;
esac
