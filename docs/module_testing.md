# Module Packaging: Manual Test Checklist

## Purpose

This checklist verifies the change that made `aop_wiki_cli` an installable module
([issue #5](https://github.com/gingin77/aop_wiki_cli/issues/5)). Before that change the tool ran only from a clone with
the working directory set to the repo root; now it installs from a Git URL, exposes an `aop-wiki-cli` command, and
resolves every input, output, cache and log path against a configurable data directory.

Run it after any change that touches the package layout, the entry point, or `src/aop_wiki_cli/paths.py`. Steps 1 and 2
run from the clone; steps 3 through 5 confirm the installed tool works from anywhere.

The unit tests (`uv run pytest`) do not cover any of this — they exercise search functions, not packaging — so this
checklist is the only thing standing between a layout change and a broken install.

---

## 1. From the clone (the development path still works)

```bash
cd ~/Developer/aop_wiki_cli
uv sync
uv run pytest
uv run aop-wiki-cli --help          # should list all 8 commands
uv run python -m aop_wiki_cli --help
```

**Expected:** the test suite passes, and both invocations print the same command list.

---

## 2. No bare relative paths remain

```bash
grep -rn --include="*.py" -E "'(outputs|inputs|logs|xml_inputs)/|\"(outputs|inputs|logs|xml_inputs)/" src/
```

**Expected:** no output. Any hit is a path that would resolve against the caller's working directory instead of the
data directory, which is exactly what the packaging change removed.

---

## 3. Install it as a tool

`uvx --from` against the local checkout is the same code path as the Git URL, so it can be checked before pushing.

```bash
uvx --from "$PWD" aop-wiki-cli --help     # no install, like uvx --from git+...
uv tool install --force "$PWD"            # puts aop-wiki-cli on PATH
aop-wiki-cli --help
```

Once the branch is on `main`, the published form is:

```bash
uvx --from git+https://github.com/gingin77/aop_wiki_cli aop-wiki-cli --help
uv tool install git+https://github.com/gingin77/aop_wiki_cli
```

**Note:** if `aop-wiki-cli` is not found after the install, run `uv tool update-shell` and open a new shell.

---

## 4. Run every command from a directory that is not the repo

This is the real test: the commands must find their own configs, workbook and curated inputs without a clone anywhere
in sight, and must write only under the data directory.

```bash
mkdir -p /tmp/aop-test && cd /tmp/aop-test

# Optional: reuse the XML you already have instead of a 49MB download.
# The filename is keyed to today's date.
mkdir -p xml_inputs
cp ~/Developer/aop_wiki_cli/xml_inputs/aop-wiki-xml-2026-08-06 \
   xml_inputs/aop-wiki-xml-$(date +%Y-%m-%d)

aop-wiki-cli collect-event-integration-rankings
aop-wiki-cli collect-ker-analytics
aop-wiki-cli find-kers-for-events --ke-ids 1346 --limit 5
aop-wiki-cli search-kers-for-concordance-text
aop-wiki-cli harmonize-ker-evidence
aop-wiki-cli search-with-config methods_nams
aop-wiki-cli search-with-config lung_and_immune_aops   # exercises the entities_and_fields path
aop-wiki-cli collect-harmonized-seizure-aops           # uses the shipped workbook + curated files

echo '{"a": {"input_term": "x", "matched_term": "y", "match_score": 0.95}}' > m.json
aop-wiki-cli manually-review-matches m.json --threshold 0.5

find . -type d -maxdepth 2   # outputs/, xml_inputs/, logs/ all under /tmp/aop-test
```

**Expected:** all eight commands complete, and nothing is written outside `/tmp/aop-test`.

**Note:** `collect-harmonized-seizure-aops` runs without prompting because the curated files ship in the wheel. Add
`--skip-curated` to confirm the two interactive review stages still work.

---

## 5. Data-directory precedence

The data directory is chosen in this order: `--data-dir`, then `$AOP_WIKI_CLI_DATA_DIR`, then the current directory.

```bash
cd /tmp/aop-test
aop-wiki-cli --data-dir /tmp/aop-alt collect-event-integration-rankings
ls /tmp/aop-alt                      # outputs/, logs/, xml_inputs/ land here instead

AOP_WIKI_CLI_DATA_DIR=/tmp/aop-env aop-wiki-cli collect-ker-analytics
ls /tmp/aop-env
```

**Expected:** each run writes under the directory it was given, not under `/tmp/aop-test`.

---

## Cleanup

```bash
uv tool uninstall aop-wiki-cli
rm -rf /tmp/aop-test /tmp/aop-alt /tmp/aop-env
```

---

## Broader coverage

`bash test_cli_integration.sh` from the clone drives the same commands through the console script and honors
`AOP_WIKI_CLI_DATA_DIR`. It is slower than this checklist because it forces a couple of cache refreshes, but it also
checks the shape of the search output JSON.
