# Security policy

Vocatron runs on your own machine and processes the files you give it. It starts local programs
(ffmpeg, fdkaac and its own worker processes), downloads pinned AI models over HTTPS and checks
their SHA-256, and asks the public lyrics service LRCLIB for lyrics unless you turn the lookup off
(`lyrics.lookup: false`). It has no server and no account.

## Report a problem

Please report a security problem privately, not in a public issue: use GitHub's "Report a
vulnerability" (Security tab of this repository). Say what you found, how to reproduce it and which
version (`vocatron --version`) you used. I will answer as soon as I can; this is a one-person
project, so there is no fixed response time.

## Supported versions

Only the latest release gets fixes.
