# Write the Video Script Series

Turn each reviewed brief into a 3-5 minute audience-facing video script based on the same claims and evidence as its paired article.

For each piece, provide structured Markdown containing narration, approximate timing, scene direction, on-screen text, visual suggestions, and evidence references. Target roughly 450-650 spoken words.

- Open and close with the authorized avatar; use information graphics, maps, cases, and source cards in the middle.
- Preserve claim IDs and exact evidence versions.
- Do not introduce facts or stronger certainty than the paired brief supports.
- Make uncertainty, commercial incentives, and important limitations audible to the viewer.
- Add source and article-link placeholders for the YouTube description.
- Include a disclosure that the avatar and cloned voice are AI-generated and authorized by the author.

Return one structured JSON object containing `piece_id`, `title`, `markdown`, and all brief `claim_ids`. The component writes the Markdown file and JSONL manifest.
