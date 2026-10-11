# Select Eligible Evidence

Apply the snapshotted project brief and editorial policy to every eligible item supplied on stdin.

Return one JSON object with a `decisions` array containing exactly one decision for each supplied item, in the same order. Each decision has these fields:

- `item_id`
- `version_id`
- `decision`: `accept`, `reject`, or `defer`
- `reason`: a concise, evidence-specific explanation
- `piece_ids`: an array containing any of `01`, `02`, and `03`; use an empty array for `reject` and `defer`
- `scores`: integer scores from 0 to 2 for audience relevance, evidence directness, claim-specific credibility, novelty, and perspective contribution
- `claim_cluster_id`: a stable label when several items repeat the same underlying announcement or claim, otherwise `null`
- `uncertainties`: an array of unresolved questions

Do not treat reputation, popularity, repetition, or model confidence as proof. Attribute company claims as claims. Defer rather than guess when access, dates, identity, methods, or corroboration are unresolved. Return only the structured JSON object. Never omit an item, including items you reject or defer.
