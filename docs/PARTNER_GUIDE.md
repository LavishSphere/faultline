# Yaseen's guide: working on FAULTLINE with Claude Code

You don't need to know programming. Your agent writes the code; you bring the finance and the math.
You work on tasks the leads give you, and every change goes to the leads as a "pull request" (PR) for review before it counts.

## One-time setup (about 15 minutes)
1. Accept the GitHub invite to `LavishSphere/faultline` (check your email / github.com/notifications).
2. Install tools (Mac, in Terminal):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # if you don't have Homebrew
   brew install git gh python@3.12 node
   gh auth login            # choose GitHub.com → HTTPS → login with browser
   gh auth setup-git
   ```
   **On Windows:** install [Git for Windows](https://git-scm.com/download/win) (includes Git Bash), the GitHub CLI
   (`winget install GitHub.cli`), and Python 3.12 from python.org (tick "Add to PATH"). Run the commands below in **Git Bash**.
   If you cloned before 2026-11-13, after your next `make pull` restore the raw data files once (nobody edits these by
   hand, so nothing is lost): `rm -rf services/api/data/raw services/api/markets/testdata && git checkout -- services/api/data/raw services/api/markets/testdata`.
3. Install Claude Code: see https://docs.claude.com/en/docs/claude-code/setup (or the VS Code extension).
4. Get the project:
   ```bash
   gh repo clone LavishSphere/faultline ~/faultline
   cd ~/faultline && claude
   ```
   The first message from the session will say "You are working for Yaseen (role: PARTNER)" and list your tasks.
   If it says it couldn't find your GitHub login, ask the agent to help you run `gh auth login`.


## ⚠️ Golden rule: pull before you edit anything
**Always get the latest version from GitHub before you or Claude change anything.** Others are changing the project
at the same time; editing an old copy creates conflicts. In Terminal:
```bash
cd ~/faultline && make pull
```
(`make pull` is our safe version of `git pull`: it gets the latest `main` from GitHub and puts your work on top of it.
If your Mac says `make: command not found`, run `xcode-select --install` once, or use `bash scripts/pull.sh`, which does the same.)
Claude also checks this before every edit and will stop and say "pull first" if your copy is out of date.
If you see that, just say: **"pull the latest and continue"**.

## Every working session
1. `cd ~/faultline && make pull && claude`. Pull first, then start Claude.
2. Type **`/start-task`** (or `/start-task 12` for issue #12). The agent checks the task came from a lead, makes a branch, and explains the plan.
3. Work with it in plain English: "the receivables lag should be 2 weeks for B2B customers", "show me week-by-week cash for case B".
4. When done, type **`/ship-pr`**. It runs the tests, updates from GitHub, and opens the PR. Send the link to the lead.
5. If the lead asks for changes, open the session, say "address the review on my PR", then `/ship-pr` again.

## Working on several tasks at once
When Claude's first message lists more than one task as **(ready)**, type **`/my-sprint`**. Claude explains which tasks can run
side by side (they must not touch the same files), and after you say go, it runs one specialist agent per task in parallel.
Each one opens its own PR. You get back a summary of each PR in plain language, plus any **questions for you** about the finance.
Answer those; they need your judgment. Tasks marked *(waiting on #N)* start automatically once the lead merges #N.

## What the agent will not do (by design)
- Work on something that isn't a delegated task. Ask a lead to create an issue.
- Merge, deploy, or change `main`. Only leads do that, after review.
- Edit the project's rules files (`.claude/`, `.github/`).

## Your areas
Financial assumptions and parameters (`docs/MATH_MODEL.md` §10), formula correctness (§1–§4, §8), golden test cases,
optimizer constraints and disruption costs, review of real historical cases, and accuracy of the VC research summaries.

## Words you'll hear
- **Branch**: your own draft copy of the project; nothing you do there affects the real version.
- **Commit**: a saved checkpoint on your branch.
- **Pull request (PR)**: "please review my draft and add it to the real version." Leads decide.
- **Test**: a small program that checks a calculation gives the hand-computed answer.
- **main**: the real, reviewed version of the project.
