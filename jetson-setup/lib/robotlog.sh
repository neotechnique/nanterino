# robotlog.sh - central logging for every bash script on this Jetson.
# Usage (first line after the shebang):  source /opt/robot/lib/robotlog.sh "<component>"
# Writes UTC ISO-8601 lines to /var/log/robot/<component>.log; WARN/ERROR also go to
# /var/log/robot/errors.log with an incident id, entry script and parent chain.
RL_DIR=/var/log/robot
RL_COMPONENT="${1:-$(basename "${BASH_SOURCE[1]:-$0}" .sh)}"
RL_SCRIPT="$(realpath "${BASH_SOURCE[1]:-$0}" 2>/dev/null || echo "$0")"
RL_PARENT="${ROBOT_PARENT:-none}"
rl_log() {
  local level="$1"; shift
  local line
  line="$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ) $level [$RL_COMPONENT] pid=$$ script=$RL_SCRIPT parent=$RL_PARENT $*"
  echo "$line" >> "$RL_DIR/$RL_COMPONENT.log" 2>/dev/null
  case "$level" in
    WARN|ERROR) echo "$line" >> "$RL_DIR/errors.log" 2>/dev/null; echo "$line" >&2 ;;
    *) echo "$line" ;;
  esac
}
log_info()  { rl_log INFO "$@"; }
log_warn()  { rl_log WARN "$@"; }
log_error() { rl_log ERROR "incident=$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM $*"; }
set -o errtrace
# A failing command is a warning (scripts may test things on purpose); a non-zero exit is an error.
trap 'rl_log WARN "command failed rc=$? line=$LINENO cmd=$BASH_COMMAND"' ERR
trap 'rc=$?; if [ $rc -ne 0 ]; then log_error "exit=$rc"; else rl_log INFO "end exit=0"; fi' EXIT
export ROBOT_PARENT="$RL_SCRIPT"   # children see who launched them
rl_log INFO "start"
