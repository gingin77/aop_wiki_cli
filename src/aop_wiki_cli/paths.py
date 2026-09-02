"""Resolution of every filesystem root the CLI reads from or writes to.

Nothing in this package should build a path out of a bare relative string.
Import time must not decide where data lives either: an installed tool is
started from arbitrary directories, and the data directory is only known once
the CLI callback has read ``--data-dir`` and the environment. Every helper here
therefore resolves lazily, at call time.

Precedence for the data directory:

1. ``--data-dir`` on the command line (via :func:`set_data_dir`)
2. the ``AOP_WIKI_CLI_DATA_DIR`` environment variable
3. the current working directory

Files that ship inside the wheel (curated review inputs, the Behl seizure
workbook) are resolved with :mod:`importlib.resources` through
:func:`package_data_path`, and may be overridden by a copy the user drops into
their own data directory.
"""
import os
from importlib import resources
from pathlib import Path
from typing import Optional

ENV_VAR = "AOP_WIKI_CLI_DATA_DIR"

# Set once by the CLI callback; None means "fall back to env var, then cwd".
_data_dir_override: Optional[Path] = None


def set_data_dir(data_dir) -> Path:
    """Pin the data directory for the rest of the process."""
    global _data_dir_override
    _data_dir_override = Path(data_dir).expanduser().resolve()
    return _data_dir_override


def get_data_dir() -> Path:
    """Root under which all inputs, outputs, caches and logs live."""
    if _data_dir_override is not None:
        return _data_dir_override

    from_env = os.environ.get(ENV_VAR)
    if from_env:
        return Path(from_env).expanduser().resolve()

    return Path.cwd()


def data_subdir(*parts) -> Path:
    """A path under the data directory, e.g. ``data_subdir('outputs', 'cache')``."""
    return get_data_dir().joinpath(*parts)


def outputs_dir(*parts) -> Path:
    """Where generated results are written."""
    return data_subdir('outputs', *parts)


def cache_root() -> Path:
    """Root of the dated entity caches shared by the collection commands."""
    return outputs_dir('cache')


def logs_dir() -> Path:
    """Where log files are written."""
    return data_subdir('logs')


def xml_inputs_dir() -> Path:
    """Where downloaded AOP-Wiki XML exports are kept."""
    return data_subdir('xml_inputs')


def inputs_dir(*parts) -> Path:
    """Where user-supplied input files are looked for."""
    return data_subdir('inputs', *parts)


def curated_dir(*parts) -> Path:
    """Where user-curated review inputs are looked for."""
    return data_subdir('curated', *parts)


def ensure_dir(path) -> Path:
    """Create ``path`` (and parents) if needed and return it as a Path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_data_path(*parts) -> Path:
    """A file shipped inside the package under ``aop_wiki_cli/data/``."""
    return Path(resources.files('aop_wiki_cli').joinpath('data', *parts))


def bundled_input(data_dir_path: Path, *package_parts) -> Path:
    """Prefer a user-supplied copy of a shipped file, else the shipped one.

    ``data_dir_path`` is where a user would place their own version; the
    packaged copy under ``aop_wiki_cli/data/`` is the fallback so the command
    still runs outside a clone.
    """
    if Path(data_dir_path).exists():
        return Path(data_dir_path)
    return package_data_path(*package_parts)


def seizure_workbook_path() -> Path:
    """The Behl seizure supplementary data workbook."""
    return bundled_input(
        inputs_dir('seizure_aops', 'behl_seizure_supp_data.xlsx'),
        'seizure_aops', 'behl_seizure_supp_data.xlsx',
    )


def curated_input_path(filename: str) -> Path:
    """A curated, human-reviewed mapping file used by the seizure workflow."""
    return bundled_input(curated_dir(filename), 'curated', filename)
