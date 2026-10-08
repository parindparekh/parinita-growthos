# AEO / GEO in GrowthOS v1.6

GrowthOS treats answer-engine visibility as an observation and provenance problem, not as a guaranteed ranking channel.

## Executable surfaces
- Governed claim manifest: `/aeo/claims/{content_id}.json`
- Conservative Schema.org JSON-LD: `/aeo/content/{content_id}.jsonld`
- Query library: `/v1/aeo/queries`
- Recorded observations: `/v1/aeo/probes`
- Configurable licensed REST probe: `/v1/aeo/probes/run`
- Visibility/citation analysis: `/v1/aeo/visibility`
- Heuristic recommendations: `/v1/aeo/recommendations`
- Claim Graph: `/v1/content/{content_id}/claim-graph`

## v1.6 addition
Exact citation URLs in recorded AEO observations can be connected to the same source nodes that support approved GrowthOS claims. This shows that an answer engine cited the exact source URI; it does not prove the engine learned the claim from a GrowthOS release or that the release caused the citation.

## Opportunity loop
AEO visibility gaps feed Signal's Opportunity Queue. That can recommend reviewing missing prompts, earned-media sources or governed claim publication. Any resulting content still passes normal GrowthOS proof, approval, Chrysalis and distribution controls.
