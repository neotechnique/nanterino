#!/usr/bin/env bash
# Run the Nanterino graph test suites (brain_graph, graph_visual, graph_features, graph_vars, graph_vars2, registries,
# properties, nodes_n1 (lot N1), nodes_n2 (lot N2: parity nodes), nodes_n3 (lot N3: per-theme parity), snapshot jobs, web assets, web modules); one `== <suite> exit=<rc> <s>s` line per suite plus its
# summary lines, exit 1 if any suite failed.
#
# Boundary: offline suites only (no browser; the editor web suite is tests/web/run.py, driven by
#           /opt/robot/scripts/l7_scenarios.sh). Logs of each suite: /tmp/graph-tests-<suite>.log.
# Entry   : /opt/robot/scripts/nanterino-graph-tests.sh sources this file after loading robotlog (log_info);
#           run directly, log_info is a no-op. Moved into the repo in lot M7 (2026-11-02).
type log_info >/dev/null 2>&1 || log_info() { :; }

cd /opt/robot/nanterino || exit 2
rc=0
for t in test_brain_graph test_graph_visual test_graph_features test_graph_vars test_graph_vars2 test_nodes_registry test_vartypes_registry test_properties test_nodes_n1 test_nodes_n2 test_nodes_n3 test_graph_snapshot_jobs test_web_assets test_web_modules; do
  start=$(date +%s)
  # G3: 700 s per suite (was 400): brain_graph runs 85 real-time traces + the no-trap tests (~470 s), graph_visual
  # replays the same 85 traces on the compiled graph
  timeout 700 .venv/bin/python -m tests.$t > /tmp/graph-tests-$t.log 2>&1
  r=$?
  [ $r -ne 0 ] && rc=1
  log_info "$t exit=$r $(( $(date +%s) - start ))s"
  echo "== $t exit=$r $(( $(date +%s) - start ))s"
  grep -E "^(FAIL|ran |trace parity|extra tests|compiled-graph parity|parity |graph_visual tests|graph_features tests|graph_vars tests|graph_vars2 tests|nodes_registry tests|vartypes_registry tests|properties tests|nodes_n1 tests|nodes_n2 tests|nodes_n3 tests|graph_snapshot_jobs tests|web_assets tests|web_modules tests|passed|  variables drawing)" /tmp/graph-tests-$t.log
done
exit $rc
