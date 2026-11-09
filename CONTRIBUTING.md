# Contributing

Thanks for helping. The short version: fork, branch, `scripts/check`, pull
request, and CI must pass.

## The rules that matter

- **Never commit Novation's firmware**, a decoded or patched image, or
  anything under `firmware/` (except its README) or `work/`. Each user
  downloads the official file from Novation (`scripts/fetch-firmware.sh`).
  CI refuses a pull request that adds such a file, and the optional hooks
  (`scripts/install-hooks.sh`) refuse it before the commit.
- **Findings carry addresses and a confidence label** (observed, emulated or
  inferred). An inference is never presented as an observation.
- **Hardware is the maintainer's.** Pull requests are checked by the tests
  and the simulator. Before a release, the maintainer flashes the build to
  a Summit, runs the test rig and records the result in
  [docs/hardware-log.md](docs/hardware-log.md). If you flash your own
  build, you do it at your own risk ([README](README.md)); reports are
  welcome as an issue.

## Making a change

1. **Fork** the repository and clone your fork. Setup, with pinned
   versions: [docs/SETUP.md](docs/SETUP.md). You need Docker, git and a
   browser.
2. **Branch** from `main`, one topic per branch.
3. **Get the firmware** so the full suite runs (it stays in `firmware/`,
   git-ignored):

   ```bash
   scripts/fetch-firmware.sh
   ```

4. **Check** before you push. This is what CI runs:

   ```bash
   scripts/check
   ```

   `scripts/check --quick` skips the long simulator plays while you work.
   A change to `patches/mpe/` also needs the web descriptor re-exported
   ([docs/web.md](docs/web.md#the-descriptor)); the tests fail while it is
   stale.
5. **Open a pull request** against `main`. CI must pass. Say what changed and
   why; for firmware work, cite addresses.

## Commits

- Subject line in the imperative, at most 72 characters ("Map Summit
  settings menu tables").
- The body says why, and what was observed or inferred.
- Keep findings, symbols and the [PLAN](docs/PLAN.md) checkbox they tick in
  the same commit.

If a firmware file was ever staged, even when the commit was refused,
`git add` has already copied it into the local object database. No push
sends it, because nothing references it, but remove it anyway:

```bash
git prune --expire=now
```

## Releases

The maintainer runs the **Release** workflow (Actions → Release) with the
version and, first, `dry_run`. It runs the checks with the firmware,
builds the web patcher, and then tags the commit, creates the GitHub
Release (no firmware attached) and deploys the page to GitHub Pages
([docs/web.md](docs/web.md#deploying-to-github-pages)). A release follows
the hardware run of that build.
