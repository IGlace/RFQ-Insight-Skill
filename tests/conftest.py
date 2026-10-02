"""Make the skill's scripts importable from the repo-root test suite.

`plugins/rfq-insight/` is the installable plugin, so it carries no tests and
no conftest of its own. Putting its skill's scripts/ on sys.path here lets the
tests import both the `rfq` package and the top-level CLI scripts
(`import validate`, `import finalize`, ...) exactly as the skill runs them.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_ROOT = os.path.join(REPO_ROOT, "plugins", "rfq-insight", "skills", "rfq-insight")
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
