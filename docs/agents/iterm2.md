# iTerm2 panes

Read this guide before you open, brief or close an iTerm2 pane, and before you decide where a worker runs. Each pane is a split of a pane already on screen, of one type:

- **Worker pane**: a Claude session where an Opus worker changes code, configuration, tooling or tests and runs its own Codex review loop, each review as a background task.
- **Command pane**: a pane where you run a command other than a worker's Claude session, such as Codex, in the same grid and under the same cap as the worker panes.

The **pane script**, `~/.claude/francis-setup/pane`, opens, closes, reads, types into and lists the panes. It is one file per machine, which a `/francis-setup` run with scope Global writes. It works from the coordinator's own iTerm2 session, the **main pane**. Its id is the part of `ITERM_SESSION_ID` after the colon, `${ITERM_SESSION_ID#*:}`. Some launchers drop iTerm2's variables, such as Claude Code 2.1.330 started through its `ClaudeCode.app` bundle. When `ITERM_SESSION_ID` is not set, find the id once by hand: run `it2 session list`, find your own row by its name, which is your Claude session's name plus ` (claude)`, or by your tty, and take its first column. Then put `FRANCIS_PANE_MAIN=<id>` before each pane script command, such as `FRANCIS_PANE_MAIN=<id> ~/.claude/francis-setup/pane list`. The script refuses an id that `it2 session list` does not show, and `ITERM_SESSION_ID` wins when both are set. A worker reads the main pane's id from its brief, and that id is the same one.

## Where a worker runs

Check in this order, and take the first case that holds:

1. Neither `ITERM_SESSION_ID` nor `FRANCIS_PANE_MAIN` gives a main pane: the worker runs in-process.
2. `test -x ~/.claude/francis-setup/pane` fails: the worker runs in-process, and you tell the user in one line that this machine lacks the pane script and that a `/francis-setup` run with scope Global installs it.
3. Otherwise the worker runs in a worker pane.

An in-process worker is a sub-agent with the same model, effort and brief, and you say in one line where it runs. It runs the same Codex review ([Codex review](agent-workflow.md#codex-review)). A worker whose work needs an extra Claude flag runs in-process only as "Extra Claude flags" in "Worker pane" says.

## Layout

Worker panes and command panes fill numbered slots right of the main pane. Slot 1 takes the right half of the window, slot 2 stacks below it, slot 3 opens right of slot 1 and slot 4 right of slot 2.

```text
+-----------+-----------+-----------+
| main      | Slot 1    | Slot 3    |
|           |           |           |
|           +-----------+-----------+
|           | Slot 2    | Slot 4    |
|           |           |           |
+-----------+-----------+-----------+
```

The pane script picks the pane to split: each open splits the pane that covers the lowest free slot, also after panes closed in any order, and the main pane keeps its width. The new pane can take a higher slot than the lowest free one, and the slots always match the panes' positions. `it2` has no resize command, so the user drags a divider to resize. [Concurrency](agent-workflow.md#concurrency) caps how many workers run; the cap counts worker panes and command panes together, and the script refuses an open past it.

Some closes leave a layout where no split keeps every pane at its slot, such as the main pane widened beside two stacked panes. The open then refuses before any split and names the pane to close: close it (after its work is done), then open again. An open also refuses while a pane that an older script opened is open, because that pane has no slot; every other command still works on it.

## Pane script

```bash
~/.claude/francis-setup/pane open-worker --profile 'SAKURA' --mode auto --cap 4 --settings .claude/worker-settings.json <checkout> <branch> <effort> [-- <claude-flag>...]
~/.claude/francis-setup/pane open-cmd --profile 'SAKURA' --cap 4 [--name <name>] [--dir <dir>] <command>...
~/.claude/francis-setup/pane close <pane-id>
~/.claude/francis-setup/pane read <pane-id> [<lines>]
~/.claude/francis-setup/pane send <pane-id> <text> [--enter]
~/.claude/francis-setup/pane press <pane-id> <key>
~/.claude/francis-setup/pane waiting
~/.claude/francis-setup/pane list
```

- **Open** (`open-worker`) splits a pane, returns keyboard focus to the main pane, names and records the new pane, changes to `<checkout>` and starts Claude in it. It then waits up to 30 seconds for Claude's mode line in the new pane and prints one line, `<type><TAB><pane-id><TAB><name><TAB><ready|not-ready>` ("After an open"). The name is also the Claude session's name, the address for `SendMessage`. Each word after `--` goes to Claude unchanged, shell-quoted, after the script's own flags ("Extra Claude flags" in "Worker pane"). The open refuses, with exit 1 and before it splits a pane, a word that is a flag the script sets itself: `-n`, `--name`, `--model`, `--effort`, `--permission-mode` or `--settings`, also in the `--flag=value` form.
- **Open-cmd** opens a command pane the same way, changes to `<dir>` (default: your current folder) and runs `<command>`, each word shell-quoted alone, so each word reaches the program unchanged. It waits for nothing and prints `cmd<TAB><pane-id><TAB><name>`. The name is `<name>`, or "Command N: <last path part of the first word>" with the lowest free N. A missing `<dir>` is refused before any split.
- **Close**, **Read**, **Send** and **Press** take a worker pane or a command pane that the script opened and still lists, and refuse any other id and the main pane.
- **Close** closes the pane.
- **Read** prints the last 40 lines of a pane's screen, or `<lines>` lines, as UTF-8 text such as `❯`, without invalid bytes, box-drawing and block characters, control characters or blank lines. Every pane read in this guide uses it.
- **Send** types `<text>`; with `--enter` it then sends a carriage return on its own, which a Codex prompt needs to accept the text.
- **Press** sends one key: a single printable character, `Enter`, `Escape`, `Tab`, `Up`, `Down`, `Left` or `Right`. Any other key name exits 2 and sends nothing.
- **List** prints the open panes, one line each, `<type><TAB><pane-id><TAB><name>`, oldest first: the worker panes (type `worker`), then the command panes (type `cmd`).
- **Waiting** prints the line that list prints for each open pane whose screen shows a prompt that waits for an answer: Claude's "Do you want to proceed?", Codex's "Would you like to run the following command?" or "Allow Browser use to access". With no such pane it prints nothing. Read a listed pane to see what the prompt asks.
- An error prints a message and exits non-zero. A message that names a `/francis-setup` run with scope Global means the script on this machine is older than this guide: tell the user, and run the worker in-process, or, for a worker whose work needs an extra Claude flag, as "Extra Claude flags" in "Worker pane" says.

`it2`, iTerm2's CLI, answers the folder trust dialog and closes a notice ("After an open"). When `command -v it2` finds nothing, call it as `/Applications/iTerm.app/Contents/Resources/utilities/it2`.

## After an open

The last field of the open's line says whether Claude's mode line showed in the new pane within 30 seconds: `ready` or `not-ready`.

1. `ready`: go on to step 3, with no pane read.
2. `not-ready`: read the pane, `~/.claude/francis-setup/pane read <pane-id>`, and act on the dialog it shows:
   - **The folder trust dialog**: the script does not recognise it, so `not-ready` is often that dialog. Check that it names `<checkout>`, then choose the option that trusts the folder: `it2 session send $'\x1b[B' --session <pane-id>` moves down one option and `it2 session send $'\r' --session <pane-id>` confirms. Read the pane after each key.
   - **A notice**, a dialog that only informs and offers a key to close it: close it with Esc, `it2 session send $'\x1b' --session <pane-id>`, read the pane again, and tell the user in one line what the notice said.
   - **A dialog that asks for a choice**, such as a grant, a login or an install: leave the answer to the user. Tell the user what the dialog asks, send no brief, and keep the pane open; the steps below wait for the user.
   Go on when the pane shows Claude's input prompt and the mode line `auto mode on`.
3. Send the brief with `SendMessage` and `notify_when_idle: true`, to the name the open printed.

Observed with Claude Code 2.1.327: a "Claude in Chrome" notice showed one time on an open without `--chrome`, and Esc closed it; the extra Claude flag `--add-dir` shows a confirmation before the mode line. Not verified: whether the notice comes back after a Claude update.

## Idle notices

Every `SendMessage` that carries a message to a pane sets `notify_when_idle: true`, so you get an idle notice when the pane's session ends a turn. A subscription gives exactly one notice; after it fires, no subscription is left. You learn that a pane has finished from its report or from a notice; read a pane only as this section and "After an open" say.

A notice whose turn-end time is earlier than the last report you accepted from that pane, or a notice for a pane that is already closed, needs no pane read.

A notice whose quote says the session waits on a background task it started, such as its Codex review, needs no pane read either: at once, start the timer of the third case below. Read the pane when the quote is absent, is cut off before it says what the session waits for, or says anything else.

On any other idle notice, read the pane one time (`pane read <pane-id>`), then act on what it shows:

- **The report arrived**: check it, and go on to close the pane.
- **The session stopped on an error, or needs the user**: tell the user. The pane stays open.
- **The session waits on a background task**, such as its Codex review: do not subscribe again, because a subscription to an idle session fires at once; the timer is what catches a worker that stops later. When the repo has agent-inbox, start the fallback timer, as [With agent-inbox](#with-agent-inbox) says. Otherwise start a 20-minute timer as a background task (`sleep 1200`); when the report arrives first, stop the timer, and when the timer ends first, read the pane one time:
  - still waiting: start the timer again;
  - busy: subscribe again, with a `SendMessage` that sets `notify_when_idle: true` and has no message;
  - stopped: tell the user.

A pane read can show text under the `❯` prompt in the pane's input line: text the user typed and did not send. Tell the user, and leave the text as it is.

What a notice does, as observed with Claude Code 2.1.325:

- It reaches you only after your own turn ends, never between your tool calls. Wait for it by ending your turn.
- It fires at once when the session ends its turn while its background task still runs.
- A subscription to a session that is already idle fires at once, so it tells you nothing while a worker waits.
- It quotes the session's last message, but that quote can be absent.
- It can arrive after the report it is about.
- Not verified: what a notice says when a session exits, and when it stops on an API error. In both cases the pane read and `pane list` show the state.

### With agent-inbox

When the repo has agent-inbox ([agent-inbox](agent-workflow.md#agent-inbox)), the wait task is the first signal that a worker's review ended: the worker's codex-review sends the coordinator its run report, and the wait task exits soon after the run ends (5 to 7 seconds in agent-inbox's trial 2). In place of the 20-minute timer, run one fallback timer, a 60-minute background task (`sleep 3600`). It catches a worker that stopped and sent no report. When the worker's report arrives, stop the fallback timer.

When the wait task exits:

1. Run `agent-inbox read`.
2. For each run report, subscribe to that worker again, with a `SendMessage` that sets `notify_when_idle: true` and has no message, so that its next idle notice reaches you while it fixes the findings or reports. Then stop the fallback timer and start it again.
3. Start the wait task again.

When the fallback timer ends, check the state with `agent-inbox list` or `agent-inbox top`, not with a pane read, and take the first case that holds:

- the state of the worker's review run is working: start the timer again;
- the state of the worker is working: subscribe again, with a `SendMessage` that sets `notify_when_idle: true` and has no message, and start the timer again;
- the state of the worker is idle, blocked, error or gone, and it sent no report: tell the user.

## Worker pane

Only a worker, an agent that changes code, configuration, tooling or tests, runs in a worker pane. Doc edits and exploration stay in-process sonnet sub-agents ([Sub-agent models](agent-workflow.md#sub-agent-models)).

**Open.** Run `open-worker` with `<checkout>` the work branch's worktree, `<branch>` the work branch, and `<effort>` from the model table in [agent-workflow.md](agent-workflow.md#sub-agent-models). The worker runs as Opus with that effort, in permission mode `auto`.

`--settings` gives the worker the allow rules of the **worker settings file**, `.claude/worker-settings.json`: the repo's check commands and the commands every worker runs (git reads, `git add`, `git commit`, `git merge`, codex-review, `gh issue view` and the review timer). The path is relative to `<checkout>`, so a worktree uses the copy its branch tracks. The open refuses when `<checkout>` lacks the file, before it splits a pane: tell the user, and run the worker in-process. A change to the file is a permission change ([Permission settings](agent-workflow.md#permission-settings)).

**Extra Claude flags.** Add an extra Claude flag to one open only when that worker's work needs a Claude feature that the default launch lacks. Put `--` after `<effort>`, then each flag and its value as separate words: `-- --chrome` for work that needs Claude in Chrome, such as a browser check. An extra Claude flag that changes permissions is a permission change ([Permission settings](agent-workflow.md#permission-settings)): ask the user before you pass one. When the work needs an extra Claude flag and no worker pane can open (no iTerm2 session, no pane script, or a script older than this guide), run the worker in-process only when your own session already has the feature. Otherwise tell the user why, and do not start that worker.

Auto mode approves routine actions without a prompt, because nothing should stop a worker: its `git` and codex-review commands run without the user pressing a key in the pane. Its classifier still blocks risky actions.

**Brief.** Send the brief a sub-agent gets ([Sub-agent briefs](agent-workflow.md#sub-agent-briefs)) with `SendMessage` and `notify_when_idle: true`, plus the main pane's id. The worker runs its own Codex review loop, each review as a background task ([Codex review](agent-workflow.md#codex-review)), and reports back with `SendMessage` to the `from` address of the brief message it received, so a renamed coordinator session still gets the report.

**Close.** When the report arrives, check it against the brief and check that Codex approved. Then close the pane with `pane close <pane-id>`. A pane that stopped on a problem (review cap reached, failed check, needs the user) stays open, and the report names it.

## Command pane

Open a command pane to run a command other than a worker's Claude session, such as Codex, where you can watch it: `open-cmd` with the command and its arguments as separate words. Type into it with `pane send <pane-id> <text> --enter`, see whether it waits on a prompt with `pane waiting`, answer the prompt with `pane press <pane-id> <key>`, read it with `pane read <pane-id>`, and close it with `pane close <pane-id>` when its work is done. It counts toward the cap, so close it before you open a worker pane in its place.

## Browser check pane

Run a check in Chrome, such as a manual checklist or a browser audit, with codex-chrome in a command pane. It starts Codex on the extension-backed Chrome route, because Codex's default browser route fails with "The browser access host is unavailable". Write the check's steps to a prompt file, then open the pane with both full paths, since `~/.claude/francis-setup/` is not on `PATH`:

```bash
~/.claude/francis-setup/pane open-cmd --profile 'SAKURA' --cap 4 ~/.claude/francis-setup/codex-chrome [--model <m>] [--effort <e>] [--repo <dir>] <prompt-file> <writable-dir> <start-url>
```

Codex runs in `<repo>` (default: the pane's folder) with model `gpt-6.2-astra` at effort `high`, unless `--model` and `--effort` say otherwise, in the `workspace-write` sandbox with `<writable-dir>` writable too. Its prompt tells it to follow `<prompt-file>`, open `<start-url>` in a new tab of its own, leave the user's other tabs alone and close its tab at the end. A relative path resolves against the pane's folder. When `test -x ~/.claude/francis-setup/codex-chrome` fails, tell the user in one line that this machine lacks codex-chrome and that a `/francis-setup` run with scope Global installs it.

Known limits:

- The first visit to a new origin shows "Allow Browser use to access <origin>?" in the pane, and Codex waits for your answer; `pane waiting` lists the pane while it waits.
- If `browsers.list()` is empty, check that the Codex Chrome extension and its native host are installed. Both were absent on the Mac used for the manual check.
- No switch turns JavaScript off, so a step that needs JavaScript off comes back "not checked".
