"""Check that the programs Vocatron needs outside Python are installed.

Run by ``make setup``. Prints what is missing and exits non-zero when something is. The judgement
is the one ``vocatron doctor`` uses (``vocatron.core.system``).
"""

import sys

from vocatron.core.system import encoder_problems, fdkaac_check, ffmpeg_problems
from vocatron.engines.system import LocalSystemProbe


def main() -> int:
    """Print the findings and return the process exit code."""
    probe = LocalSystemProbe()
    problems = ffmpeg_problems(probe.ffmpeg_version())
    if not problems:
        problems += encoder_problems(probe.ffmpeg_encoders())
    fdkaac = fdkaac_check(probe.fdkaac_version(), "fdkaac")
    problems += [fdkaac.fix] if fdkaac.fix else []
    for problem in problems:
        print(f"MISSING: {problem}", file=sys.stderr)
    if not problems:
        print("ffmpeg with libass and libx264, fdkaac: ok")
        print("Next: run 'vocatron doctor' to check the GPU and the models.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
