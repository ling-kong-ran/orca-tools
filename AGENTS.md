# Repository operation policy

Use `python scripts/git-vps-time.py` instead of plain `git` when running Git in
this repository, especially commit/tag/merge/push. The verified receiving VPS
uses UTC; the wrapper sets the Git process timezone to UTC without changing the
Windows timezone. Do not set author or committer dates to the workstation zone.

Do not rewrite existing commit history or rename tracked assets as a side effect
of timestamp privacy changes. Those actions change commit IDs or asset references
and require a separately scoped migration. Git fetch/pull do not transfer source
filesystem mtimes; transferred render outputs use the VPS receiver timestamp.
