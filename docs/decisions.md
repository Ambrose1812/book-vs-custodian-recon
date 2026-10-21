# Design decisions

One entry per decision: the question, what I chose, what I rejected, and what it costs.
Newest first.

## Scoring the recon on detection date, not just detection
- **Question:** how do I know the recon works when the custodian feed is simulated?
- **Chose:** plant known errors and score the recon against an answer key. The test fails on a missed break, a false alarm on a clean control, or a first flag on the wrong day.
- **Rejected:** only checking that each planted security is flagged on any day. That passes a recon that flags the right security for the wrong reason, or weeks late.
- **Costs:** the answer key is a simulation fixture and cannot exist for real data, so it proves the logic, not real-world coverage. Break type is not asserted, because one planted cause can legitimately show up under more than one status.

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

## Known risks not yet handled
- If a later custodian feed omits a row an earlier ingest contained, staging keeps the old row, because the latest ingest wins per record. Not a problem with a fixed seed and unchanged inputs; worth a test.
