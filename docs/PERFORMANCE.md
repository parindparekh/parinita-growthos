# Performance and learning loop

GrowthOS normalizes outcome telemetry rather than hard-coding one analytics vendor.

`POST /v1/performance/events` accepts impressions, views, reach, engagements, likes, comments, shares, clicks, conversions,
watch_seconds, downloads, mentions and citations. Events may identify a release, destination and channel.

`GET /v1/performance` aggregates totals and computes transparent CTR, engagement and conversion rates.
`GET /v1/performance/learn` adds deterministic recommendations with minimum-data thresholds. It explicitly does not infer
causation from correlation.

Provider-specific metric collectors should map their native API into this envelope. This release provides the destination
adapters for transmission but does not claim automatic metric pull for every provider.
