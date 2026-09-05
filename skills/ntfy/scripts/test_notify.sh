#!/usr/bin/env bash
# Offline checks: exported curl function prevents all network requests.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export NTFY_TOPIC=agent-test
export MOCK_STATUS=200 MOCK_EXIT=0
export EXPECT_BODY=$'@literal body\nsecond line'
export EXPECT_TITLE='Title: Task complete' EXPECT_PRIORITY='Priority: default' EXPECT_TAGS='Tags: '

curl() {
  local body argument
  local title_seen=0 priority_seen=0 tags_seen=0 body_seen=0
  body=$(cat)
  [[ $body == "$EXPECT_BODY" && ${!#} == https://ntfy.sh/agent-test ]] || return 90
  [[ $1 == --disable ]] || return 91
  for argument in "$@"; do
    [[ $argument != "$EXPECT_TITLE" ]] || title_seen=1
    [[ $argument != "$EXPECT_PRIORITY" ]] || priority_seen=1
    [[ $argument != "$EXPECT_TAGS" ]] || tags_seen=1
    [[ $argument != @- ]] || body_seen=1
  done
  (( title_seen && priority_seen && tags_seen && body_seen )) || return 92
  printf '%s' "$MOCK_STATUS"
  return "$MOCK_EXIT"
}
export -f curl

bash "$script_dir/notify.sh" "$EXPECT_BODY" 'Task complete'
export EXPECT_PRIORITY='Priority: urgent' EXPECT_TAGS='Tags: warning,skull'
bash "$script_dir/notify.sh" "$EXPECT_BODY" 'Task complete' urgent warning,skull
export EXPECT_PRIORITY='Priority: default' EXPECT_TAGS='Tags: '

expect_failure() {
  local expected=$1 actual=0
  shift
  "$@" >/dev/null 2>&1 || actual=$?
  [[ $actual == "$expected" ]] || {
    printf 'Expected exit %s, got %s\n' "$expected" "$actual" >&2
    exit 1
  }
}
expect_failure 2 env -u NTFY_TOPIC bash "$script_dir/notify.sh" hello
expect_failure 2 env NTFY_TOPIC= bash "$script_dir/notify.sh" hello
expect_failure 2 env NTFY_TOPIC='bad/topic' bash "$script_dir/notify.sh" hello
expect_failure 2 bash "$script_dir/notify.sh"
expect_failure 2 bash "$script_dir/notify.sh" ''
expect_failure 2 bash "$script_dir/notify.sh" hello $'Bad\r\nTitle'
expect_failure 2 bash "$script_dir/notify.sh" hello Title invalid
expect_failure 1 env MOCK_EXIT=22 bash "$script_dir/notify.sh" "$EXPECT_BODY" 'Task complete'
expect_failure 1 env MOCK_EXIT=28 bash "$script_dir/notify.sh" "$EXPECT_BODY" 'Task complete'
expect_failure 1 env MOCK_STATUS=302 bash "$script_dir/notify.sh" "$EXPECT_BODY" 'Task complete'
printf '%s\n' 'All offline notification checks passed.'
