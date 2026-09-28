# 9.4.2-beta.1 lifecycle follow-up — unpublished

## Failed candidate evidence is retained

Repair Acceptance run 36435373102 at source 7464d4b4c609aa19ad18299c53492b92ee2ac414 passed installation, native reports/control/reopen and File Exit, but its 24-cycle repetition finished **23 passed, 1 failed**. Cycle 4 raised Windows ConnectionAbortedError 10053 during the project-switch/exit sequence. The original harness did not record the exact failing request phase; the log alone is not conclusive proof of that transport failure's cause. The gate correctly skipped update replacement and installer publication. Do not distribute that earlier installer as accepted.

Evidence artifact 10976410900, SHA-256 62e7c2f3ac46aba814878810ed4d44a4e1d564c15378e611f32d867c16cf6391, was downloaded and independently hashed. No timeout cycle was retried away. A passing native-close cycle took 13.219 seconds; its passive stacks captured an in-flight Foundry Local catalog call while desktop shutdown waited for the server and later native runtime unloading. This establishes an observed slow status path, not the cause of every earlier intermittent timeout.

## Independently reproduced response-ordering defect

The original HTTP Exit used a 150 ms timer before stopping the application. A new deterministic test exercises the actual application and buffering middleware with a 220 ms outer send delay. The exact old source fails because shutdown happens before the final body has been sent. A route-level BackgroundTask was also evaluated and rejected: inner response completion does not guarantee outer delivery through BaseHTTPMiddleware.

The correction registers an outer ASGI middleware last, and only the explicit local POST Exit route marks its internal request scope. Successful final transport send and full inner application completion precede orderly shutdown; error/unmarked/other requests and failed transport sends do not trigger it. The callback runs off the event loop. The endpoint's access policy is unchanged. Eight tests cover ordering and rejected paths.

## Bounded, isolated status inspection

Foundry capability probing now uses a private child process with a four-second query deadline and bounded owned-process cleanup. On Windows only that probe PID's process tree is targeted, not applications by name or unrelated processes. Native SDK initialization is no longer loaded into the main process merely to populate the status tile. Malformed/oversized/nonlocal or wrongly identified results fail closed. Probe timeout is explicitly unknown readiness; it does not claim a cached model is ready or request a model download.

In-process actual inference/explicit model enablement remains separate; its accuracy and active-work cancellation are not claimed tested by these status checks. Concurrent forced status requests coalesce after a shared completed refresh. The main status route no longer calls the shared probe once before asking FieldBookSync to call it again. Fourteen regression cases include actual successful and blocked child processes, owned Windows cleanup arguments, negative response contracts and refresh coalescing.

## Verification before the next Windows run

Fresh local Linux regression selection: **614 passed, 1 skipped**. Documentation/static quality and source compilation passed. The exact-original ordering reproduction was separately recorded as an expected failing test before restoring the repair. These are not completed Windows acceptance results for the new revision.

The lifecycle harness now records the failing phase and traceback while keeping every cycle and the unchanged 15-second exit deadline. No automatic request retry was added. The same four Windows/external acceptance workflows, 24 candidate cycles and three real update fixtures remain mandatory. The prior 24/24 baseline remains historical evidence, not a substitute. Stable main/update feeds, tags and the user's installed 9.4.1 remain untouched. Production signing, optional software packaging and real-field/provider boundaries remain explicit.
