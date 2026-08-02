## What this changes

<!-- One or two sentences. What is different after this is merged? -->

## Why

<!-- The problem being solved. Link the issue if there is one. -->

## Notes for reviewers

<!-- Anything non-obvious: a trade-off you made, an alternative you rejected,
     a constraint from the engine or a provider that forced the shape. -->

## Checklist

- [ ] `pytest` passes in the services I touched
- [ ] `ruff check .` is clean
- [ ] New behaviour is covered by a test (including the denial path, for
      authorization changes)
- [ ] Documentation updated in this change
- [ ] An ADR is added or updated, if this changes the tenancy model, the
      authorization model, the engine boundary or the data flow
