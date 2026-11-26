# termrenamer

## Language

**Coordinator**:
The main agent that owns the session, delegates the work to sub-agents, runs the git steps itself, and edits no repository files beyond a trivial fix, a permission settings change the user approved, or a release script's output.
_Avoid_: orchestrator, manager, lead

**Verdict**:
Codex's final message in a review, ending in `VERDICT: APPROVED` or `VERDICT: CHANGES REQUESTED`. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: result, output, review log

**Work size**:
How much process a change needs, fixed at the end of a grill: small, specced, or ticketed. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: tier, scope, level

**Check log**:
The file in the session's scratchpad that holds the whole output of one run of the repo's checks or tests. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: run log, test log, output file

**Intermittent failure**:
A failure that passes on a rerun with no change that explains it. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: flaky test, flake, noise

**Manual checklist**:
The steps a person runs on the repo's local build to check a change that a reader can see, each step on a real page or screen. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: QA list, test plan, browser checklist

**Run report**:
The message that `agent-inbox run` sends to the session that `--report-to` names when a headless run ends, such as a Codex review: the exit code, the verdict, and the last lines of the output when the run failed. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: review notice, wake

**Wait task**:
The coordinator's background task that runs `agent-inbox wait` and exits when an unread message arrives, such as a run report. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: inbox watcher, review timer

**Worker**:
The Opus agent that changes code, configuration, tooling or tests and runs its own Codex review loop, in a worker pane or in-process. See [Agent workflow](docs/agents/agent-workflow.md).
_Avoid_: implementer, coder, executor

**Worker pane**:
The iTerm2 pane where a worker runs as a Claude session, in the grid of up to two columns and two rows right of the main pane, each Codex review as a background task. See [iTerm2 panes](docs/agents/iterm2.md).
_Avoid_: implementer pane, panel, tab, window

**Command pane**:
The iTerm2 pane where the coordinator runs a command other than a worker's Claude session, such as Codex, in the same grid and under the same cap as the worker panes. See [iTerm2 panes](docs/agents/iterm2.md).
_Avoid_: cmd pane, shell pane, raw pane
