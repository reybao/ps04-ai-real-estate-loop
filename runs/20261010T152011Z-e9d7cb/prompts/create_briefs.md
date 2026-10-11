# Create Three Evidence-Based Briefs

Use accepted decisions, the eligible evidence, and the snapshotted project brief to produce exactly three distinct brief records with piece IDs `01`, `02`, and `03`. Return one JSON object with a `briefs` array in that order.

Each JSON object must include:

- `piece_id`, `title`, `question`, `argument`, `synthesis`, and `limitations`
- `claims`, an array whose members contain `claim_id`, `statement`, `type`, and `evidence`
- claim types limited to `reported_fact`, `source_claim`, and `inference`
- evidence references containing the exact `item_id`, `version_id`, and a resolvable locator

Use text locators with an exact supporting quote and media locators with a retained transcript `segment_id`. Explain how evidence supports each inference. Surface conflicting evidence and commercial incentives. If accepted evidence cannot support all three briefs, state the limitation clearly in the briefs rather than inventing sources. Return only the structured JSON object.

Before returning, check each brief separately: its claims must cite at least three distinct `publisher_id` values from accepted evidence. All cited quotes must be copied verbatim from the supplied source excerpts. Do not count two items from the same publisher as independent sources.
