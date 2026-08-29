# Project State Authority

OnlyAlpha treats current engineering progression as a controlled fact, not as prose copied independently across documents.

## Authority

The repository-root `project-state.toml` is the sole authoring authority for current project-control state:

- current milestone and milestone state;
- last verified increment;
- active increment, if any;
- next authorized increment, if any;

`README.md`, `docs/roadmap.md` and `docs/p9_k_stateful_kernel_protocol_boundary.md` are deterministic projections of that authority for their current-status fields. They must not independently author those facts.

Historical implementation reports under `docs/reports/` remain historical evidence. They may record the state and evidence that existed when the report was written, but they are not current project-state authority.

## Commands

Check projection consistency:

```bash
uv run python scripts/project_state.py check
```

Render all current projections from the authority:

```bash
uv run python scripts/project_state.py render
```

Start the exactly authorized next increment:

```bash
uv run python scripts/project_state.py transition start P9.K.6
```

Verify the active increment and authorize its successor:

```bash
uv run python scripts/project_state.py transition verify P9.K.6 \
  --next-id P9.K.7 \
  --next-name "Remote Protocol Foundation"
```

The transition commands are compare-and-swap style operations. They fail closed when the requested transition does not match the current authority state.

## Invariants

```text
One current engineering fact
→ one authoring authority
→ deterministic projections

Projection drift
→ fail closed

Unexpected transition
→ fail closed

Historical report
!= current project-state authority

Task Gate evidence
!= Phase Gate evidence
```

Do not add a second manually maintained current-state file. Do not solve projection drift by weakening the architecture check. Change the authority, render the projections, and review the resulting diff.

The authority deliberately remains small. Git history, ADRs, implementation reports and test/CI results continue to own
historical/design/evidence facts; they must not be duplicated into `project-state.toml` merely for convenience. Historical certification
artifacts remain historical records only and are never current progression inputs.
