# Git Remotes: Adding a Second (Private) Remote

## Purpose

This note is written from the public **`aop_wiki_cli`** clone — the one whose `origin` is the public project
(`gingin77/aop_wiki_cli`). In that clone you add a second remote named `private` pointing at the private repository
`gingin77/<private-repo>`, so work can be pushed to either without a second clone. (In a clone of `<private-repo>`
itself, `origin` is already that private repo, so the names below are reversed.)

A remote is just a name mapped to a URL. Adding one changes nothing about your branches or history until you
explicitly `push` or `fetch` against it.

---

## 1. See the remotes you have

```bash
git remote -v
```

**Expected (before adding the private remote):**

```text
origin  https://github.com/gingin77/aop_wiki_cli.git (fetch)
origin  https://github.com/gingin77/aop_wiki_cli.git (push)
```

`-v` ("verbose") shows the URL behind each name, and separate `fetch` and `push` lines because a remote can, in
principle, read from one URL and write to another.

---

## 2. Add the private repository as a second remote

```bash
git remote add private https://github.com/gingin77/<private-repo>.git
```

`private` is the local nickname; any name would work, but `private` reads clearly next to `origin`. This command
is local only and prints nothing on success.

---

## 3. Confirm the remote was added

```bash
git remote -v
```

**Expected (after adding it):**

```text
origin  https://github.com/gingin77/aop_wiki_cli.git (fetch)
origin  https://github.com/gingin77/aop_wiki_cli.git (push)
private https://github.com/gingin77/<private-repo>.git (fetch)
private https://github.com/gingin77/<private-repo>.git (push)
```

---

## Working with the two remotes

```bash
# Download the private repo's branches without changing yours (they appear as private/<branch>)
git fetch private

# Push the current branch to the private repo
git push private <branch>

# Push and set the private remote as this branch's default upstream,
# so later `git push` / `git pull` on this branch use `private` automatically
git push -u private <branch>

# Which remote is a branch tracking?
git branch -vv
```

**Note:** `<private-repo>` is a separate repository with its own history, not an empty mirror of this one. A
branch here will not fast-forward onto its `main` unless the histories share commits, so push feature branches and
open a pull request there rather than pushing straight to its `main`.

---

## Fixing and removing remotes

```bash
# Correct a URL you typed wrong
git remote set-url private https://github.com/gingin77/<private-repo>.git

# Rename a remote
git remote rename private analytics

# Remove a remote (local only; the GitHub repo is untouched)
git remote remove private
```

Removing or renaming a remote only edits this clone's `.git/config`; it never deletes anything on GitHub.
