# Git workflow

Read this guide before creating a branch or commit, or using `gh` to create or comment on pull requests, issues, or releases.

## Commit messages

Write every commit message as a Conventional Commit:

```text
<type>[(<scope>)][!]: <description>

[body]

[footers]
```

- **Type**: `feat` for a new feature, `fix` for a bug fix. Other changes take another type, such as `build`, `chore`, `ci`, `docs`, `perf`, `refactor`, `style` or `test`.
- **Scope**: optional, a noun in parentheses naming the part of the codebase, as in `fix(parser):`.
- **Description**: a short summary of the change, right after the colon and space.
- **Body**: optional free-form paragraphs, starting one blank line after the description.
- **Footers**: optional, starting one blank line after the body. Each is a token, then `: ` or ` #`, then a value, as in `Refs: #12`. A token joins its words with `-`, as in `Reviewed-by`.
- **Breaking change**: mark it with `!` directly before the colon, a `BREAKING CHANGE: <what breaks>` footer, or both. Write the footer token in uppercase; `BREAKING-CHANGE` means the same.

## Branch names

Branch names follow [Conventional Branch 1.1.0](https://conventionalbranch.org/) without its agent prefixes. Name every branch `<type>/<description>`. The trunk branches `main`, `master` and `develop` take no prefix.

- **Type**, by the purpose of the work, one of these seven and no other: `feature/` or `feat/` for a new feature, `bugfix/` or `fix/` for a bug fix, `hotfix/` for an urgent fix, `release/` to prepare a release (`release/v1.2.0`), and `chore/` for non-code work such as dependency or documentation updates.
- **Description**: lowercase letters and digits, words joined by single hyphens. A dot may sit between two letters or digits, usually in a version: `chore/upgrade-node-v20.11`.
- The description starts and ends with a letter or digit, and hyphens and dots never repeat or touch: `feature/new--login` and `release/v1.-2.0` are invalid.
- Keep it short and name the work. Include the ticket number when there is one: `feature/issue-123-new-login`. Write a ticket number in lower case, like the rest of the description: `PROJ-123` becomes `proj-123`, as in `feature/proj-123-new-login`.

## When a work branch is required

Non-trivial work happens on a work branch. Work is non-trivial when it changes any of:

- application behaviour;
- production configuration;
- build, release, or CI pipeline behaviour;
- dependencies; or
- tests.

Documentation-only work goes straight to the trunk branch. Documentation that belongs to non-trivial work goes on that work branch with the related change. After the branch's pull request is merged, follow-up documentation for that work goes straight to the trunk branch.

While an integration branch is open, documentation for its spec (decision records, glossary terms, guide changes the spec causes) goes on the integration branch, not the trunk branch. The coordinator commits it there through a worktree of the integration branch ([Worktrees](#worktrees): add it, commit, unlock and remove it), or gives it to the worker whose ticket it belongs to. Documentation that has nothing to do with the open spec still goes straight to the trunk branch.

## Worktrees

Every work branch gets its own worktree, and the main checkout stays on the trunk branch. Documentation-only work that goes straight to the trunk branch needs no worktree.

Every worktree goes in a folder beside the main checkout, named after the repo, with one folder for each branch:

```text
<parent folder of the main checkout>/<repo name>-worktrees/<branch name with each / replaced by ->
```

Add every worktree locked, with the branch as the reason. A lock keeps `git worktree prune` and a careless `git worktree remove` from deleting a worker's checkout:

```sh
git worktree add --lock --reason "<branch>" <path> <branch>          # existing branch
git worktree add --lock --reason "<branch>" -b <branch> <path> <base>  # new branch
```

For the repo `~/dev/shop` and the branch `feat/issue-12-cart`: `git worktree add --lock --reason "feat/issue-12-cart" ~/dev/shop-worktrees/feat-issue-12-cart feat/issue-12-cart`. `git worktree add` makes the `<repo name>-worktrees` folder when it is missing.

A locked worktree refuses `git worktree remove`. To clean one up, unlock it first: `git worktree unlock <path>`, then `git worktree remove <path>`.

## Safety

Change Git configuration, force-push, or skip a commit hook (`--no-verify`) only on the user's explicit instruction. When a hook rejects a commit, fix the cause and commit again.

Run a merge, a push or a tag as a command of its own, apart from any read command, so a block or a permission prompt applies to that command alone.

## Pull requests and changelog

Open a pull request from the work branch after the repo's checks pass. Keep the title in Conventional Commits form, because a squash merge uses it as the commit title.

After `gh pr create`, wait for the checks with a command that does not end on an empty list. In the first seconds GitHub reports no checks yet, so `gh pr checks <n> --watch` alone exits at once:

```sh
until gh pr checks <n> --json name -q 'length > 0' | grep -q true; do sleep 5; done; gh pr checks <n> --watch
```

Merge only after every check passed. A repo with no CI says so in its own copy of this guide, in place of this rule.

Write the body of a pull request that changes source, tests or build with the `pr` skill (`/pr`).

Link the issue in the body. The pull request that completes a spec or a ticket holds `Closes #N`, so GitHub closes the issue on merge. A pull request that does only part of one holds `Refs: #N`, so the issue stays open.

Update `Unreleased` in `CHANGELOG.md` for changes a user can see, as the repo's versioning rules say. Documentation-only changes get no entry.

## Merging a pull request

This section says how to merge, never whether. Merge a pull request, or push to the trunk branch, only when the owner asked for that merge; otherwise ask first.

Choose the method for each pull request: squash merge by default, a merge commit when the table says so. Rebase-merge stays off: GitHub rewrites every SHA and the committer, drops signature verification, adds no PR number, and puts each review-fix commit on the trunk branch.

| Choose       | When                                                                                                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Squash merge | The default. The branch is one unit of work whose commits add no history value: work in progress, fixups, review fixes, one small change.                             |
| Merge commit | Each commit is meaningful and already Conventional, such as a branch carrying several tickets that each have `Refs: #N`. Squashing would lose the per-ticket history. |

- Squash merge with `gh pr merge <n> --squash --match-head-commit <sha> --subject "<title> (#<n>)" --body "<message>"`, where `<sha>` is the pull request's head commit that the checks passed on, and `<message>` is a short plain body and the `Refs:` or `Closes` footers. The pull request head must match `<sha>` to allow the merge (`gh pr merge --help`), so a push after the checks is never merged unseen; the merge report names `<sha>`. A plain `gh pr merge <n> --squash` takes the pull request body, written for the reviewer, as the commit message.
- Write a squash commit message as a valid Conventional Commit, and pass it with the command above: keep the useful body, keep the `Refs:` and `Closes` footers.
- Merging into an integration branch that later merges to the trunk branch is the usual merge-commit case.
- State the method and the reason in one line, in the pull request or the report: `Merge method: squash, one unit of work with review fixups.`
- A ticket branch going into its integration branch is not a pull request merge. Merge the integration tip into the ticket branch with this command, so the merge commit has a Conventional subject:

  ```sh
  git merge --no-edit -m "chore: merge <integration-branch> into <ticket-branch>" <integration-branch>
  ```

  Then fast-forward the integration branch to it with `git fetch . <ticket-branch>:<integration-branch>`, which moves the integration branch without checking it out. It refuses when the move is not a fast-forward, and while a worktree has the integration branch checked out; unlock and remove such a worktree first. History stays linear.
- After the fast-forward, remove the ticket's worktree (`git worktree unlock <path>`, then `git worktree remove <path>`) and delete its branch. `git branch -d` refuses here, because it compares the ticket branch with the checked-out trunk branch, not with the integration branch. First prove the branch is contained with `git merge-base --is-ancestor <ticket-branch> <integration-branch>`; only when that succeeds, delete it with `git branch -D <ticket-branch>`.
