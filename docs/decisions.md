# Design decisions

One entry per decision: the question, what I chose, what I rejected, and what it costs.
Newest first.

## What counts as a break episode, an open break, and a match
- **Question:** how do I turn a daily list of flagged positions into something with an age?
- **Chose:** an episode is an unbroken run of break days for one security, counted in trading days, so a break from Friday into Monday is one episode. A gap of one trading day ends it, and a return starts a new episode with a fresh age. An episode is open if it is still flagged on the latest date. Match rate counts matched and timing_difference as good standing.
- **Rejected:** counting calendar days (a weekend would look like a gap), and one row per security (it would merge a break that cleared and came back into a single item).
- **Costs:** every planted error in the simulation stays unresolved, so all episodes are open and old. The aging buckets will not show a mix until the simulator can also resolve some breaks. A break that changes type while open keeps one episode, and the model records its first and last type.

## Scoring the recon on detection date, not just detection
- **Question:** how do I know the recon works when the custodian feed is simulated?
- **Chose:** plant known errors and score the recon against an answer key. The test fails on a missed break, a false alarm on a clean control, or a first flag on the wrong day.
- **Rejected:** only checking that each planted security is flagged on any day. That passes a recon that flags the right security for the wrong reason, or weeks late.
- **Costs:** the answer key is a simulation fixture and cannot exist for real data, so it proves the logic, not real-world coverage. Break type is checked only as a warning (`assert_planted_breaks_are_quantity_breaks`), because one planted cause could in principle show up under more than one status. With the current seed all 14 come out as quantity breaks, so the warning is silent. Making it a hard failure would turn a seed change into a broken build.

## Custodian feed built from prices, not from the book
- **Question:** what should the simulated custodian be built from?
- **Chose:** raw transactions plus the split-indexed prices. It never reads `fct_positions`.
- **Rejected:** copying our own positions and perturbing them. That would make the recon agree by construction, and any disagreement would be my own bug in disguise.
- **Costs:** the simulator depends on pipeline output, so the DAG needs a partial dbt build before it. The split math is read from one model, not duplicated in Python, so there is a single source of truth.

## Timing differences are not breaks
- **Question:** should a gap caused by unsettled trades count as a break?
- **Chose:** a separate `timing_difference` status when the custodian matches our settled book. Only the other statuses set `is_break`.
- **Rejected:** treating every difference as a break, which would bury real problems under T+1 noise.
- **Costs:** the settled-basis book must be modeled too, and a real break that happens to equal the settled quantity would be hidden for a day.

## Recon as a full outer join
- **Question:** which join keeps securities that exist on only one side?
- **Chose:** a full outer join on security and date, with absent treated as zero.
- **Rejected:** an inner join, which silently drops missing-on-custodian and missing-in-book rows, the most common real breaks.
- **Costs:** the model has to treat nulls as zero and filter out dates where neither side holds anything.

## Splits on an as-of basis
- **Question:** should share counts be restated to today's terms or reported as of each date?
- **Chose:** as-of, because a custodian statement for a date uses that date's share count and raw prices.
- **Rejected:** back-adjusted shares and prices, which suit return calculations. Mixing one adjusted side with one raw side would be a silent error.
- **Costs:** the query is harder, and a trade on the ex-date is deliberately not adjusted.

## The pipeline creates its own `raw` schema
- **Question:** who creates the `raw` schema in a new database?
- **Chose:** the loader runs `CREATE SCHEMA IF NOT EXISTS raw` inside the load transaction.
- **Rejected:** creating it by hand once, as I did on the first run. A clean clone failed at `load_reference_data` with `schema "raw" does not exist`, which is how I found the gap.
- **Costs:** one extra statement per load, and the loader now needs permission to create schemas.

## Known risks not yet handled
- If a later custodian feed omits a row an earlier ingest contained, staging keeps the old row, because the latest ingest wins per record. Not a problem with a fixed seed and unchanged inputs; worth a test.
