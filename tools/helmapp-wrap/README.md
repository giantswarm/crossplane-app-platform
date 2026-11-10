# helmapp-wrap

Moves one Flux `HelmRelease` under a `HelmApp`, as in [docs/migration.md](../../docs/migration.md).

```
uv run --directory tools/helmapp-wrap helmapp-wrap plan --context <mc-ctx> -n <ns> <helmrelease> --app <app> -o helmapp.yaml
uv run --directory tools/helmapp-wrap helmapp-wrap delete-suspended --context <mc-ctx> -n <ns> <helmrelease> [--yes]
```

- `plan` changes nothing. It reads the HelmRelease, its OCIRepository and (for an in-cluster HelmRelease) the
  MC name, then writes the HelmApp manifest and prints the case (A or B), the warnings and the steps.
  It exits with code 2 and a `stop:` line when a stop condition of docs/migration.md is true.
- `delete-suspended` is the only cluster write (Case B step 3, rollback step 3). It deletes the HelmRelease only
  when `spec.suspend` is `true` and the object has a prune guard annotation. Without `--yes` it is a dry run.

The git steps stay manual: the tool does not know the git source of the HelmRelease. Do the READ checks
from docs/migration.md; the tool does not run `helm history` on the workload cluster.

Tests: `make test-wrap`.
