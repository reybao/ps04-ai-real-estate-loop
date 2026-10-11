# Write the Article Series

Turn each reviewed brief into one audience-facing article of approximately 600-900 words, excluding references.

- Preserve the brief's central argument, limitations, claim IDs, and exact evidence versions.
- Clearly distinguish verified facts, attributed source claims, and the author's synthesis.
- Explain technical real-estate, infrastructure, power, and AI terms for the target audience.
- Do not add facts, numbers, quotations, or certainty that are absent from the retained evidence.
- Address the strongest relevant counterargument or uncertainty.
- Include an `As of` date matching the run and a readable source-notes section.
- Keep internal claim markers inspectable while also giving readers understandable citations.

Return one structured JSON object containing `piece_id`, `title`, `markdown`, and all brief `claim_ids`. The component writes the Markdown file and JSONL manifest.
