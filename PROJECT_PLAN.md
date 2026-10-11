# MIT 1.125 Problem Set 4: Project Direction and Editorial Standards

This project builds a repeatable intelligence pipeline for developments published in the preceding 30 days about U.S. commercial real estate, PropTech, and AI data centers. It is not a general AI-news digest or a stock-picking service. Its central question is how AI may change real-estate work and how land, power, construction, financing, and regulation affect the infrastructure on which AI depends.

This is a planning document. The assignment contracts are in `README.md` and `ARCHITECTURE.md`; the implemented policy is in `config/editorial_policy.md`. The actual decisions and publications must be judged against the retained run artifacts, not against proposed examples in this plan.

## Topic and audience

- **Working publication name:** The AI Real Estate Loop
- **Topic:** AI for Real Estate and Real Estate for AI
- **Primary scope:** U.S. commercial real estate, PropTech, AI data centers, and the land and power infrastructure behind them
- **Audience:** Real-estate, architecture, and engineering students and early-career professionals interested in AI and the built environment
- **Recurring question:** Which developments in the preceding 30 days materially changed how AI is used in real estate or how real-estate and infrastructure constraints shape AI growth?
- **Reader value:** Separate verifiable developments from company promotion and repeated coverage; provide a framework readers can revisit in later editions
- **Editorial voice:** Clear, measured, accessible, and evidence-led, with uncertainty visible

The project settings are stored in `config/project.json`. The scope includes AI applications in valuation, leasing, asset management, property operations, and real-estate data workflows; PropTech adoption and independent evaluation; data-center land transactions, powered land, interconnection, power contracts, permitting, construction capacity, capital structure, delays, and community effects.

General AI news without a built-environment connection, routine residential-market reports, short-term stock recommendations, unsupported promotional claims, inaccessible headline-only items, and lists of unrelated stories are outside the scope.

## Freshness and coverage

Each live run fixes an actual UTC `as_of_date` at its start. Eligible source material must have been published from that date minus 29 calendar days through the run date, inclusive. For the October 9, 2026 run, the window is September 10 through October 9, 2026.

- Save `published_at` separately from `retrieved_at`.
- Exclude an item with an unknown, invalid, or future publication date from substantive evidence.
- A refreshed page date or re-uploaded old recording is not a new development.
- When a recent source discusses an older event, state what was newly reported or learned.
- Publications must use the as-of date of the run that supplied their evidence.
- An unchanged version from an earlier run may still be used if it remains inside the new 30-day window.

The assignment minimum is 12 distinct substantive items from six independent sources, including at least two substantive written RSS items, two YouTube videos, and two podcast episodes. A useful target before selection is roughly 18–24 candidate items so that weak material can be rejected. A podcast and its YouTube copy count as one underlying item; an RSS entry pointing to an episode is a discovery route, not additional evidence.

| Input | Planning target | Main contribution |
| --- | ---: | --- |
| RSS and written reporting | 6–8 | Dates, amounts, project status, policies, and research findings |
| YouTube | 3–4 | Practitioner explanation, project views, and community perspectives |
| Podcasts | 3–4 | Attributed expertise, operating experience, and competing interpretations |

## Source credibility and editorial decisions

Credibility is specific to a claim and its supporting passage. Publisher reputation, audience size, views, subscribers, and model confidence cannot establish that a particular assertion is true.

| Illustrative tier | Source type | Appropriate use |
| --- | --- | --- |
| A | Government and regulator records, grid-operator documents, local planning files, formal research, filings, and original project documents | Verifiable project status, amounts, capacity, dates, and approvals within the document's scope |
| B | Independent reporting with named sources, clear sourcing, and methods | Reported facts, context, interviews, and challenge to interested-party claims |
| C | Identifiable practitioner podcasts, interviews, conferences, training, and case accounts | Attributed experience and interpretation, not universal outcomes |
| D | Company releases, vendor demonstrations, investment commentary, and anonymous promotional channels | What the interested party claims; effectiveness and feasibility require separate evidence |

First require a relevant, dated, substantive, accessible item with an identifiable originating publisher. Audio and video must yield timestamped transcript segments. Reject duplicate versions and cross-platform copies as extra items. The implemented policy then scores audience relevance, evidence directness, claim-specific credibility, novelty, and perspective contribution from 0 to 2 each. An item scoring 8–10 is normally accepted when it supports a clear claim. Defer unresolved identity, methods, access, date, or corroboration; reject off-topic, repetitive, or unsupported promotional items.

Do not impose a minimum view count. Popularity can indicate that a narrative is circulating, not that it is accurate. A low-view local hearing can be more valuable than a viral commentary video. Shorts are mainly discovery leads unless they contain verifiable original evidence.

Company announcements can establish that a company announced or intends something; they do not independently establish project delivery, product effectiveness, or investment returns. Several articles repeating one announcement form one underlying claim cluster rather than independent corroboration. When sources disagree, compare dates, markets, methods, definitions, and incentives before drawing a conclusion. Preserve unresolved uncertainty in briefs, articles, and videos.

## Duplicate handling and independence

Use native YouTube IDs or podcast GUIDs, canonical URLs, publisher/title/date combinations, content hashes, and transcript similarity to identify duplicate observations. A duplicated recording has one stable `item_id`, even if discovered from multiple feeds or platforms. Distinguish item-level duplication from several sources repeating one underlying claim.

Different channels owned by the same producer, syndication copies, and accounts from the same company do not automatically count as independent publishers. Prefer the source closest to the original evidence; count another report as an independent contribution only when it adds reporting, data, an interview, a counterexample, or analysis. Record any uncertain independence judgment for human review.

## Initial source leads, not accepted evidence

The following links were considered during planning. Their inclusion here does **not** mean they passed the run's date, accessibility, identity, or editorial checks. The live pipeline must obtain substantive content and evaluate each candidate again.

### Written and RSS leads

- [CRE Daily PropTech](https://www.credaily.com/briefs/?_sectors=proptech) and [CRE Daily RSS](https://www.credaily.com/feed/)
- [TechRadar RSS](https://www.techradar.com/feeds.xml) and [Inman RSS](https://feeds.feedburner.com/inmannews)
- [Entrata AI announcement](https://www.entrata.com/press/entrata-pro-puts-ai-to-work-without-leaving-the-operating-system)
- [Inman PropTech reporting](https://www.inman.com/2026/10/07/tech-roundup-inside-real-estate-cotality/)
- [Data Center Frontier on powered land](https://www.datacenterfrontier.com/hyperscale/article/55409162/brookfields-arep-deal-extends-the-ai-infrastructure-stack-to-powered-land)
- [Axios on data-center power](https://www.axios.com/2026/10/08/data-centers-power-regime)
- [TechRadar on a delayed data-center grid review](https://www.techradar.com/pro/a-meaningful-risk-oracles-massive-1-3-gw-wisconsin-ai-campus-faces-severe-power-delays-as-grid-review-restarts-pushing-customer-delivery-past-2027)
- [Research lead on generative AI in real-estate marketing](https://arxiv.org/abs/2609.12684)

### Podcast and YouTube leads

- [Altus Group CRE Exchange on AI in CRE](https://www.altusgroup.com/podcasts/cre-exchange-ai-in-cre-whats-real-whats-hype-and-what-readiness-looks-like/)
- [Institutional Real Estate podcast episodes](https://muckrack.com/podcast/institutional-real-estate-inc-podcast/episodes/)
- [Blockspace on power and AI investment](https://blockspace.media/podcast/google-taps-constellation-for-3-6-gw-morgan-stanley-is-bullish-bloom-energy-b-rileys-new-ai-stock-valuation-model/)
- [Morgan Stanley, Thoughts on the Market](https://podscan.fm/podcasts/thoughts-on-the-market/episodes/will-midterms-test-the-ai-investment-cycle)
- [RPR Commercial AI video](https://www.youtube.com/watch?v=44C2m-g_gtI)
- [Power and data-center siting interview](https://www.youtube.com/watch?v=zJG_J6fmr20)
- [Water and electricity explainer](https://www.youtube.com/watch?v=m9duvzaGdpw)
- [Burlington data-center discussion](https://www.youtube.com/watch?v=pYJ0nVqV1Lc)

Perspectives to seek actively include utilities, grid operators, public utility regulators, local planners, elected officials, neighboring residents, community organizations, CRE end users, property managers, independent researchers, engineers, construction labor, and water and environmental specialists.

## Three-piece series

The pre-run concept was one piece on AI for commercial real estate, one on real estate for AI, and one connecting the two. Actual claims should follow the evidence rather than force those preliminary titles. The October 9 draft run produced:

1. **A Data Center Site Isn’t Powered Just Because Power Is Nearby.** The distinction between a nearby line, a planned power project, and power deliverable to a specific parcel. A storage-cost estimate is relevant background, not proof of site readiness.
2. **From Land to Load: The Risks Between Announcement and Operation.** Environmental review, utility approvals, project status, and community questions that may intervene between a land announcement and an operating campus.
3. **AI in Real Estate: Adoption Is Not the Same as Proof of Impact.** Recent cases and practitioner observations do not yet establish broad adoption or measured productivity gains in CRE.

Each article should be roughly 600–900 words, have a distinct central argument, use at least three independent publishers, develop a synthesis across sources, state a meaningful limitation, and connect substantive claims to exact evidence. The third piece's modest conclusion is intentional: evidence on AI adoption in ordinary CRE work was thinner than evidence on AI infrastructure in this run. The student must decide whether that is the right final editorial choice.

## Video production

The deliverables require three audience-facing YouTube videos, one for each article, plus a separate technical demonstration. Each audience video should run about 3–5 minutes and express its article's central argument through narration and visuals rather than simply reading the article aloud.

- The current plan is an authorized personal avatar and synthesized author voice in the opening and closing, with graphics, maps, project examples, and readable source cards narrated by a consistent preset AI voice in the middle.
- No additional author recording or external voice-cloning service is planned. Only the author may consent to using their own biometric material.
- Scripts target roughly 450–650 spoken words and contain timing, narration, scene directions, on-screen text, and evidence references.
- Preserve the same evidence-based claims in each article/script pair, while adapting the presentation to viewing and listening.
- Include an explicit AI presentation disclosure and article/source links in each YouTube description.

Suggested disclosure:

> The opening and closing use an AI avatar and synthesized author voice with the author's consent. Middle narration uses a separate AI-generated preset voice. The research, editorial review, and conclusions are the author's own.

Voice clones and personal avatars are sensitive biometric assets. Use only the author's own samples, follow the platform's consent process, protect the account, and delete unused models when appropriate.

The separate 4–6-minute technical demonstration should show the architecture and `bash run.sh` entry point, trace one source to a published claim, compare the second live run, demonstrate duplicate handling or failure recovery, explain a human correction or policy revision, and discuss one architectural tradeoff.

## Human review, repeatability, and submission

- Inspect at least three accepted and three rejected or deferred decisions; compare AI reasons with the student's own judgment.
- Revise the editorial policy at least once, rerun the affected stage, and preserve the before/after policy, decisions or briefs, and explanation.
- Record each human factual correction, its reason, and its evidence.
- Only a passing `review.json` and a matching student-created `approval.json` may unlock the production package.
- Complete two live runs on different days, preserve their artifacts and costs, and show duplicate avoidance plus an honestly recorded collection failure or recovery.
- Publish three freely accessible Substack articles and three public or unlisted YouTube videos; link each pair.
- Submit the separate technical demonstration video and complete `SUBMISSION.md`, including the architecture, setup, evidence, decisions, review, limitations, and reflection.
- Keep credentials out of the submitted GitHub repository.

## Current next steps

As of October 9, 2026, the topic, source list, policy, collectors, retained evidence, storage, filtering, AI editorial and writing stages, checks, and packaging gate have been implemented. The draft run `20261009T165149Z-afdf19` generated three articles and three video scripts and passed automated review. It also recorded four incomplete YouTube extractions. One human editorial correction retained the storage material in piece 01 while making the PJM-to-storage-to-site-diligence logic clearer; this is not final publication approval.

The student should now review sources and at least six AI decisions, revise the policy, complete a second live run on a different day, compare the runs, review and approve the final three pieces, prepare the package, make the three audience videos, publish the articles and videos, complete the technical demonstration, and fill `SUBMISSION.md`. Exact commands and handoffs are in [RUN_GUIDE.md](RUN_GUIDE.md).
