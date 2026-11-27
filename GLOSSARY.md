# termrenamer

## Language

**Source**:
A file or folder the person queues for renaming, which is a backup of their own media. Example filenames in documents, comments and screenshots are plain backup-style names; test data may keep messy names where a test exercises the parser's clean-up.
_Avoid_: release, rip, torrent, scene, download (as names for these files)

**Plan**:
The immutable batch of planned renames, covering each video and its sidecars, that preview shows and apply executes unchanged. Picking a different Match or leaving a file out makes a new Plan; a Plan itself never changes.

**Preview**:
The view of a Plan that the user reviews before confirming Apply.

**Apply**:
Executing a confirmed plan on the filesystem; nothing is renamed before the user confirms.

**Mode**:
The user's choice of TV or Film, which decides how filenames are parsed, which providers apply and how destinations are laid out.

**Provider**:
An online metadata source (TMDB, TheTVDB or OMDb) that a plan looks titles up in; TV and Film accept different providers.

**Sidecar**:
A subtitle or info file (such as `.srt` or `.nfo`) that moves with the video sharing its folder and filename stem. One with no such video is unpaired, not a Sidecar: with Folder rename on, it can move as a Straggler when a video moves out of its folder, and otherwise it is left alone.

**Folder rename**:
The setting that lets a plan move media into canonical show or film folders; when off, only the filename changes in its current folder.

**Season folder**:
The `Season NN` folder inside a show's folder; TV folder rename places episodes in it unless season folders are switched off.

**Destination root**:
The folder under which folder rename builds the show or film tree, set separately for TV and Film; when unset, the tree is built in the scanned folder.
_Avoid_: destination folder, output root

**Straggler**:
A file or folder left behind in a source folder after a plan's moves, which apply can merge into the target folder.
_Avoid_: stray file

**User settings file**:
The per-user dotenv file the app reads its settings from, overridden by a `.env` in the current folder and by environment variables.
_Avoid_: config file, global .env

**Stage**:
One of the four steps a batch goes through, in order: Queue, Plan, Preview, Applied.
_Avoid_: step, phase

**Title**:
One show or film that the files in a Plan belong to. The Preview lists Titles, one row each.
_Avoid_: item, entry

**Match**:
The Provider entry a Title is tied to, which gives its files their new names. A Title the Provider found nothing for has no Match.
_Avoid_: hit, result

**Candidate**:
Another entry the Provider returned for a Title, which the user can pick as the Match instead.
_Avoid_: alternative, suggestion

**Poster**:
The Provider's image for a Match, shown for the selected Title. Showing Posters is optional.
_Avoid_: cover, artwork, thumbnail

**Left out**:
Said of a file the user removed from the Plan before Apply; Apply does not touch it. Distinct from a file Apply skips.
_Avoid_: excluded, ignored

**Not recognised**:
Said of a queued video whose name the app cannot read a title from (and, in TV Mode, a season and episode). It is listed, and Apply does not touch it. Distinct from a Title with no Match, whose name was read but which the Provider did not find.
_Avoid_: unparsed, unknown

**Name taken**:
Said of a planned rename whose new name is already used, at the destination or by an earlier file of the same Plan. A setting decides whether the Plan adds a number to the name or leaves the file where it is.

**Undo**:
Reversing the last Apply: files, Sidecars and Stragglers go back where they were. Offered once for each Apply that changed something Undo can reverse, until the user starts a new batch or quits.
_Avoid_: revert, rollback

## Agent workflow

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
