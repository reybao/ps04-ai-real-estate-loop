# Write the Video Script Series

Turn each reviewed brief into a 3-5 minute audience-facing video script based on the same claims and evidence as its paired article.

For each piece, provide structured Markdown containing narration, approximate timing, scene direction, on-screen text, visual suggestions, and evidence references. Target roughly 450-650 spoken words.

- Open and close with the authorized personal avatar and its synthesized version of the author's voice. Use a consistent preset AI narrator over information graphics, maps, cases, and source cards in the middle; do not present that narrator as the author's voice.
- Preserve claim IDs and exact evidence versions.
- Do not introduce facts or stronger certainty than the paired brief supports.
- Make uncertainty, commercial incentives, and important limitations audible to the viewer.
- Add source and article-link placeholders for the YouTube description.
- Include a disclosure that the opening and closing use an author-authorized AI avatar and synthesized author voice, while the middle narration uses a separate AI-generated preset voice.

Return one structured JSON object containing `piece_id`, `title`, `markdown`, and all brief `claim_ids`. The component writes the Markdown file and JSONL manifest.
