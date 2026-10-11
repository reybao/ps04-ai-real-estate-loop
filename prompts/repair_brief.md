# Repair One Evidence-Based Brief

The previous brief failed a deterministic evidence check. Return exactly one corrected
brief in a JSON object with a `brief` field, keeping the supplied `piece_id`.

Use the specific `validation_error` to repair the brief. Preserve valid claims and
the original editorial argument where the evidence supports them. Every claim must
cite accepted item/version pairs with an exact retained text quote or supplied
transcript segment ID. Each brief must cite at least three **distinct**
`publisher_id` values; multiple items from one publisher count only once.

Add a source only when its quoted passage or transcript segment genuinely supports
the claim. If a claim cannot be supported, narrow or replace that claim instead of
adding a decorative citation. Distinguish reported facts, attributed source claims,
and your own inferences. Do not invent evidence, dates, numbers, or quotations.
