"""GrowthOS display identities; capability IDs and permissions remain stable.

Names are checked against the known Parinita register, not a claimed exhaustive
enterprise registry. Channel specialists are qualified instances of core identities.
"""
CORE_NAMES = {'signal': 'Scout', 'pr': 'Envoy', 'media': 'Curator', 'podcast': 'Orator', 'social': 'Ripple', 'amplify': 'Broadcaster', 'engagement': 'Liaison', 'acquire': 'Magnet', 'feed': 'Courier', 'claim': 'Scribe', 'aeo': 'Cartographer', 'performance': 'Gauge', 'gate': 'Scrutineer', 'rally': 'Convenor', 'channels': 'Cadence'}
CHANNEL_NAMES = {'reddit': ('Ripple', 'Forums'), 'facebook': ('Ripple', 'Facebook'), 'instagram': ('Ripple', 'Instagram'), 'threads': ('Ripple', 'Threads'), 'pinterest': ('Ripple', 'Pinterest'), 'tiktok': ('Ripple', 'TikTok'), 'tumblr': ('Curator', 'Tumblr'), 'etsy': ('Magnet', 'Etsy'), 'shopify': ('Magnet', 'Shopify'), 'local': ('Envoy', 'Local'), 'blog': ('Curator', 'Blog'), 'newsletter': ('Curator', 'Newsletter'), 'community': ('Liaison', 'Community')}
RESERVED_NAMES = frozenset(['Forge', 'Lens', 'Marshal', 'Conductor', 'Chorus', 'Pathfinder', 'Runner', 'Weaver', 'Tracker', 'Flash', 'Investigator', 'Echo', 'Driver', 'Sutra', 'Inspector', 'Painter', 'Vigil', 'Cipher', 'Sage', 'Guardian', 'Shield', 'Sentry', 'Accord', 'Thought', 'Dispatch', 'Rainbow', 'Thread', 'Counsel', 'Ledger', 'Atlas', 'Campus', 'Editor', 'Steward', 'Switchboard', 'Registrar', 'Auditor', 'Beacon', 'Maestro', 'Orchestra', 'Nivyah', 'Lineage', 'Reach', 'Compass', 'Sentinel', 'Senitene'])

def display_name(agent_id):
    if agent_id in CHANNEL_NAMES:
        identity, channel = CHANNEL_NAMES[agent_id]
        return f"Parinita GrowthOS {identity} / {channel}"
    return f"Parinita GrowthOS {CORE_NAMES[agent_id]}"

def apply_names(manifest):
    if {n.casefold() for n in CORE_NAMES.values()} & {n.casefold() for n in RESERVED_NAMES}:
        raise ValueError("GrowthOS identity collides with the known Parinita register")
    if set(manifest) != set(CORE_NAMES) | set(CHANNEL_NAMES):
        raise ValueError("Every capability must have a registered identity")
    for agent_id, capability in manifest.items():
        capability.setdefault("legacy_name", capability["name"])
        capability["name"] = display_name(agent_id)
        capability["identity"] = (CHANNEL_NAMES[agent_id][0] if agent_id in CHANNEL_NAMES else CORE_NAMES[agent_id])
        capability["namespace"] = "parinita.growthos"
