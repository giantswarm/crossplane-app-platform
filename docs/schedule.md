# Schedule windows and the day-0 force install

HelmApp `spec.schedule.windows[]{cron, timeZone, window}` maps 1:1 to RSIP `spec.schedule[]`.
`forceInstallOutsideWindow: true` sets `reconcile.fluxcd.io/requestedAt` and `reconcile.fluxcd.io/forceAt`
to the same constant (`day-0`) on the RSIP. `status.nextWindow` copies RSIP `status.nextSchedule.when`.

## PoC assumption: "the day-0 force annotations bypass the schedule"

Confirmed by source, not by a running cluster. Checked in flux-operator v0.59.0 (`.agents_source/fo059`)
and the fluxcd/pkg `apis/meta` helper it uses (go.mod:18, v1.31.0; the local clone `pkgssa` may differ in patch level).

- `internal/controller/resourcesetinputprovider_controller.go:139`: `force := meta.ShouldHandleForceRequest(obj)`.
- `:154`: `if !scheduler.ShouldReconcile(reconcileStart) && !force {` skips the run only when the force flag is false. A forced run goes on to export tags.
- `apis/meta/annotations.go:103-107` (`ShouldHandleForceRequest`) calls `HandleAnnotationRequest` (`:126-141`). It returns true when
  `forceAt` and `requestedAt` are both present and equal, `status.lastHandledReconcileAt != requestedAt`, and
  `status.lastHandledForceAt != forceAt`. On a new RSIP both status fields are empty, so the first reconcile is forced.
  Annotation names: `annotations.go:23` (`requestedAt`) and `:32` (`forceAt`).
- The first Reconcile only adds the finalizer and requeues (`:115-118`); the force check happens on the next pass, with the annotations already in place.

Caveats:

- The force is one-shot. `lastHandledForceAt` is recorded on that first reconcile even when it fails (for example the registry is down), so a failed day-0 attempt then waits for the first window. `lastHandledReconcileAt` is set in `internal/controller/common.go:61`.
- The constant annotation stays on the RSIP forever; it does nothing after the first handling. A recreated HelmApp gets a fresh RSIP and is forced again.
- `forceInstallOutsideWindow` without any window renders no annotations (there is no schedule to bypass).

## Window length

`internal/schedule/scheduler.go:51-56`: a window above zero must be at least twice the RSIP timeout (default 2m, `api/v1/resourcesetinputprovider_types.go:287`),
else the RSIP is Stalled with `InvalidSchedule` (controller `:142-148`). `ShouldReconcile` returns true for a window of 0 (`scheduler.go:86`),
so one zero window opens the gate for every schedule. The XRD rule is therefore `duration(self.window) >= duration('4m')`, which also rejects zero.
The PRD only asks for "greater than zero".

## status.nextWindow

The RSIP sets `status.nextSchedule` only when it skips a run (controller `:153-155`, cleared at the start of every reconcile), so `nextWindow` is empty
inside a window and while the RSIP is not skipping. KCL copies the value, no clock is read.

## Tests

`make test-golden` fixtures `scheduled` (schedule mapped, `nextWindow` from an observed RSIP) and `scheduled-force` (annotations).
`make test-cel` validates a zero window against the XRD with `crossplane resource validate`, offline. A live API server rejection is not tested.
