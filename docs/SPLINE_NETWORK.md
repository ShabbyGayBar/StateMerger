# Spline-network merging

The implementation lives in the `vic3_state_merger.splines` subpackage:
`network` contains the codec/models, `geography` handles adjacency, `merge`
reconstructs routes, `validation` checks the final emitted network, and `pipeline`
resolves files and exports reviews. Import
the public models and entry points directly from `vic3_state_merger.splines`.
Models and functions are also available from `vic3_state_merger`.

The default `spline_network` stage operates on original, unmerged inputs and final
hub projections. Disable it through `--no-splines`, explicit stage selection, or
the checked-by-default GUI control. Its source stack supplies the binary network
and map support files. `map_data` and `map_objects` keep their independent stacks;
configure all affected stacks when using a custom map.

The strict version-4 codec exposes `Anchor`, `Strip`, `Connection`, and
`SplineNetwork`. `from_bytes()`/`to_bytes()` preserve a no-op input byte for byte;
`validate_references()` additionally checks chains supported by the tool's routing
model. Those checks describe implementation limits, not additional engine rules.
Unsupported schemas and fatal output-integrity/serialization errors prevent output
replacement. Broken source records that cannot be interpreted are omitted with
reconstruction diagnostics; unused source defects alone do not make a draft.

`merge_spline_network(original, original_states, final_states, original_locators,
final_locators, merge_plan, geography, *, repair_splines=True)` returns `SplineMergeResult`. State tables
are plain dictionaries (`StateRegion.to_python()`); locator tables are parsed
trees keyed by city/farm/mine/port/wood. `Geography` carries passable final-state
pairs and boundary evidence. Result fields are `network` and an explicit `status` (`complete` or `draft`);
`data` serializes the network. The transformation logs
diagnostics without mutating inputs or performing filesystem writes.

```python
from vic3_state_merger.logging_config import configure_logging
from vic3_state_merger.splines import export_spline_review

configure_logging("DEBUG", log_file="/build/spline-review/run.log")
result = export_spline_review(
    game_root="/games/Victoria 3/game",
    final_mod="/mods/StatesMerging/mod",
    merge_plan=plan,
    output="/build/spline-review/mod",
    data_dir="/build/spline-review/data",
)
print(result.status)
```

Review exports preserve the existing mod. No metadata, publication or automatic
installation is performed. Use the network with the same final map and locators
whose hashes are recorded at DEBUG level in the log. Logging configuration is
owned by the caller; importing or using the spline API does not install handlers.

## Reconstruction policy

- Final settlement locators determine required IDs and identify moved/unplaced
  hubs. Original donor states are matched by hub type/province and the merge plan.
  Reused hubs retain their donor spline coordinates, including when renamed;
  visual locators can differ from authored route endpoints. The `0.01` movement
  tolerance compares original and final locators, never locators to spline points.
  Only newly created hubs use locator coordinates. Missing source hubs, changed
  locator positions and unplaced `(-1, -1)` locators remain reconstruction
  diagnostics. Existing donor anchors retain their spline geometry even when
  visual locators are unplaced or missing. No anchor is created at `(-1, -1)`.
  The final validator independently checks declared hub anchors and locator data.
- Original logical connections form a weighted graph, with wrapped geometric
  lengths and cached Dijkstra searches inside each final state. Minimum spanning
  forests can connect its hub components. Required non-strait state pairs select
  the cheapest reachable original crossing. Straits permit existing crossings
  without requiring a land spline. Paths split at retained settlement hubs.
- New land connections use railroad type; unchanged connections keep their types.
  Obsolete hubs needed along a path become intermediate anchors. IDs and tie
  breaking are deterministic. Broken routes, semantically failing projected paths,
  unverified paths and unknown route types never enter reconstruction searches.
- Ports join that same land network. Their original donor harbor and coastal
  connections are preserved when their terminals survive normal remapping,
  including routes to a different sea hub than `naval_exit_id`. That mismatch is
  advisory. Sea-to-sea routes remain separate; missing geometry is not invented.
- Port anchors must lie in their final state's declared coastal land province.
  Default repairs relocate misplaced anchors as described below. With repairs
  disabled, a failure makes the output a draft and preserves authored geometry.
  Harbor coordinates are not tested against sea/lake pixels or sea-region
  ownership. No harbor is synthesized at a visual port locator.
- A row-wise raster scan produces sparse province boundaries, cached by content
  hashes. Point contact is excluded, horizontal wrapping follows `default.map`,
  and impassable provinces/explicit blockers are respected. Strait crossings and
  naval/canal adjacency evidence are recorded separately. Unknown rules are
  represented as missing evidence, never assumed to establish nonadjacency.
  This does not reproduce the game's terrain/navmesh engine.

## Automatic repairs

Repairs default to enabled. Disable them with CLI `--no-repair-splines`, the GUI's
**Repair spline errors** checkbox, execution configuration `"repair_splines": false`,
or keyword-only `repair_splines=False` on `StateMerger.run()`,
`merge_spline_network()`, or `export_spline_review()`. Explicit CLI/API settings
override configuration. Skipping the spline stage skips repairs. This option alone
does not change compensation or bundled-asset defaults.

- Missing declared hubs with placed locators continue to be added in both modes.
  Missing locator data and explicit `(-1, -1)` locators never generate anchors.
- Before route reconstruction, a confirmed misplaced land-port anchor moves to
  its final placed locator if that locator is in its declared coastal province.
  Otherwise it moves to the nearest province pixel center, using wrapped
  horizontal distance where configured and raster row, then column, to break ties.
  Placement is checked after float32 conversion. IDs, donor mappings, harbor
  positions, and intermediate route geometry remain intact.
- After reconstruction, confirmed nonadjacent land connections and known-type
  connections containing incompatible anchor types are removed. Only their
  orphaned strips and intermediate anchors are cleaned up; shared geometry and
  declared hubs remain.
- Unknown types and uncertain adjacency are preserved. Noncoastal declarations,
  unavailable placement evidence, remaining connectivity gaps, missing harbors,
  naval routes or sea hubs, and invalid naval exits remain diagnostics. Repairs
  do not change state declarations or visual locators and do not invent routes.

`Geography.province_spans` optionally carries sparse inclusive runs
`{province_color: [(raster_row, first_column, last_column), ...]}`. Filesystem
preparation requests the declared coastal port provinces when repairs are enabled.
Direct callers can supply these runs or populate them with
`build_geography(..., relocation_provinces=colors)` for nearest-pixel fallback;
without them, only a verified locator can provide a replacement position. Sparse
point samples remain sufficient for normal validation. No input model is mutated.

Successful `hub_added`, `port_relocated`, and `connection_removed` messages log at
INFO with IDs and reasons; relocation messages include old/new coordinates.
`spline_repair_skipped` explains missing evidence or unsupported conditions. Final
validation of the repaired binary determines completeness and existing exit codes.

## Final-network validation and evidence

Only the emitted network determines semantic validity. Validation uses a parsed
round trip of the binary, including its actual float32 coordinates. Source-file
diagnostics and unsuccessful construction attempts remain separate diagnostics.
With repairs disabled, semantically failing authored geometry is preserved after
normal ID remapping, but cannot seed new routes. This does not restore absorbed state IDs or require
keeping obsolete source routes whose terminals no longer survive projection.

The accepted sources are:

- **Captured game log:** `/home/brianli/sync/temp/error.log`, lines 1797–1829,
  SHA-256 `8455df9bc66897fa2b9fd0e9b99f5c1ffb46248be3a8f2f80e737f9740ad0d17`.
  Its game version is not recorded. This is a historical run, not a runtime test
  of the current implementation.
- **Map wiki:** [Map modding / State modding](https://vic3.paradoxwikis.com/Map_modding#State_modding),
  parsed in sibling `vic3_docs/Modding/Map modding - Victoria 3 Wiki.md`, lines
  161–171. The article version is unknown; its Spline modding section is TODO.
- **State wiki:** [State modding / Naval exit](https://vic3.paradoxwikis.com/State_modding#Naval_exit),
  parsed in `vic3_docs/Modding/State modding - Victoria 3 Wiki.txt`, lines 333–341.
  The article mentions 1.9, without a section-specific version.
- **Tutorial:** [Modding State Regions, Splines, Provinces, Cities, and Roads](https://steamcommunity.com/sharedfiles/filedetails/?id=3165669021),
  especially Mapping Hubs to their States, Naval States and Hub Types, and Editing
  Splines. The page was updated June 4, 2024, and references game version 1.6 in
  its naval-state discussion; applicability to later engines needs runtime checks.

The following diagnostic identifiers connect logged findings to their evidence:

| Rule | Check policy | Evidence |
| --- | --- | --- |
| `missing_required_hub` | Each declared hub with a placed locator has its expected anchor. An absent hub with an explicit `(-1, -1)` locator is not applicable; missing locator data is unverified. | Wiki's missing connection-node error and tutorial's state/locator ID mapping; the unplaced exception is the tool policy below. |
| `port_province` | The land-port anchor is contained by its declared port province. | Captured `travel_network_definition.cpp:371`, 16 messages naming expected and actual provinces. |
| `coastal_port_province` | The associated declared port province is coastal land. | Captured `:1171`, 14 messages rejecting a noncoastal land port province. Coast classification uses static map boundaries. |
| `hub_connectivity` | Where passable non-strait land adjacency exists, report declared hubs in separate components of the final global land graph as an advisory warning. Neighboring-state detours are allowed; this warning does not cause a draft. | Tutorial's hub-connectivity requirement, treated as advisory under the tool policy below. |
| `state_connections` | Where passable non-strait land adjacency exists, a state with anchors has at least one usable connection, including the single-hub case. | Wiki's quoted disconnected-node error, qualified by the applicability policy below. |
| `direct_state_connections` | Report a missing direct hub connection for each known passable non-strait state pair as an advisory warning. An indirect global path does not suppress the warning; this warning does not cause a draft. | Tutorial's neighboring-state connection requirement, treated as advisory under the tool policy below. |
| `land_adjacency` | Land connections do not join known nonadjacent states. Passable straits remain permitted adjacency. | Wiki and tutorial quote the engine's nonadjacent-strip error. |
| `incompatible_anchor_type` | Understood land/naval routes do not mix incompatible hub types. | Tutorial explicitly forbids mixing type-0 and type-1 hubs. |
| `port_harbor`, `harbor_route` | Coastal ports have their corresponding harbor and a naval connection to a sea hub; existing accepted types 2 and 3 remain accepted. | Wiki's missing-harbor error and harbor-to-sea route instructions. |
| `invalid_naval_exit`, `missing_sea_hub` | Naval exits name an existing sea region with a naval hub; distinguish a bad region reference from missing anchor geometry. | State wiki defines the sea-region reference; tutorial says the sea state needs its own anchor. |

Harbor coordinates are not checked against sea/lake pixels or sea-region
ownership, including for advisory warnings. The wiki
instructs overlapping the harbor and land-port anchor. The captured `:1193` error
confirms an invalid/non-sea province can affect a naval node, but does not explain
how the engine obtains that province. It does not establish a harbor-pixel test.
Exact route-destination agreement with `naval_exit_id` is also not enforced; an
authored mismatch remains a `harbor_naval_exit_mismatch` advisory.

### Land connectivity policy

**Land-spline requirements follow passable land adjacency. Straits permit
connections but do not require them. States with no passable land neighbors are
exempt from land-connectivity requirements. Hub-presence, port, naval, and
existing-route checks apply independently.**

A state with no known passable non-strait neighbors skips both `hub_connectivity`
and `state_connections`. This includes islands and mainland states whose borders
are all impassable; it does not require geographical island detection or special
state IDs. Skips log `land_connectivity_not_applicable` at INFO with category
`not_applicable`. Incomplete or uncertain adjacency evidence cannot establish an
exemption: when applicability prevents a verdict, required checks are `unverified`.
One known required land neighbor establishes applicability even if another
neighbor's crossing remains unknown.

Final `disconnected_state_hubs` findings are advisory warnings, including when
adjacency or usable paths are uncertain. They retain the hub groups and global
scope, with an `unverified` flag to identify uncertainty, and do not affect export
status. Final `missing_state_connection` findings are also advisory warnings,
retaining the state pair, crossing evidence, and an `unverified` flag when a
potential direct route has unverified semantics. The separate `unconnected_state`
check remains required and can cause a draft.

Explicit `sea` province-pair entries are straits even where their raster pixels
touch. Another passable non-strait province border can still make the same state
pair subject to the direct-connection advisory. Province and crossing blockers
remain in force. Valid authored strait routes remain usable, including as detours
in the global land graph.
Their absence does not trigger a missing-link error or forced border construction.

Construction may still assemble optional internal routes from authored geometry.
For exempt states an unsuccessful attempt logs `optional_internal_connectivity_gap`
at INFO, rather than presenting a required repair. Otherwise the construction
diagnostic remains `disconnected_state_hubs` with `scope: within_state_reconstruction`.
Applicable final hub-group diagnostics use `scope: global_land_network` and allow
paths via other states. These applicability and severity choices are explicit tool
policy, not additional claims about undocumented engine requirements.

### Unplaced locator policy

The exact horizontal locator position `(-1, -1)` exempts a hub from required-anchor
and hub-connectivity checks **only when its spline anchor is absent**. The validator
logs `unplaced_hub_skipped` with category `not_applicable` at INFO; this is neither
a passed check nor a failure. Existing spline anchors are retained and validated
normally, including connectivity and land-port placement (and optional repair), regardless of an unplaced
visual locator. Missing locator tables or entries log
`locator_validation_unavailable` as an unverified required check and keep a draft.
Neither absence nor an omitted validation argument is treated as an unused hub.

Port provinces, harbor geometry/connections, naval exits, and required direct
state adjacencies remain independent of this exception. An inactive port hub does
not waive naval requirements; existing donor harbor geometry is retained even
when its land-port anchor is absent. No missing geometry is synthesized.

This is an explicit tool policy informed by the vanilla 1.15.0 baseline: 42 missing
declared anchors had unplaced locators. That observation does not establish the
engine's complete semantics for unused hubs.

## Results and verification

Spline diagnostics use the existing `vic3_state_merger` logging configuration;
there is no separate report file. CLI users can save logs with `--log-file` and
include all details with `--log-level DEBUG`. GUI file logging includes DEBUG
records when enabled. With GUI logging disabled, the draft notice explains how
to enable logging and rerun.

Final validation logs use the `vic3_state_merger.splines.validation` logger.
Confirmed `game_rule` violations and `implementation` limitations log at ERROR;
`unverified` required checks log at WARNING. Messages retain the diagnostic kind,
category, rule/check identifiers, and context, including states, anchors, port
coordinates, sampled/expected provinces, and failure reasons. Unknown route types
remain preserved when remappable, with unverified semantics. Potential connections
through unverified paths prevent missing evidence from being mislabeled as a
confirmed connectivity failure.
Global `disconnected_state_hubs` and final `missing_state_connection` findings log
at WARNING with category `advisory` and never count as validation failures, even
when their `unverified` flag is true. Unavailable adjacency and unverified existing
route semantics remain required checks and can independently cause a draft.
`validate_final_network(network, states, geography, *, locators=None)` returns a
boolean independently of logging levels or handlers. `locators` accepts normalized
`{hub_type: {state_id: (x, z)}}` positions, as returned by `locator_positions()`;
the merge pipeline supplies its final locator snapshot automatically. Direct
callers must supply these positions to verify hub activity; omission leaves the
relevant checks unverified.

Reconstruction warnings and advisories log at WARNING and do not determine
status. Optional internal gaps and not-applicable checks log at INFO. Node changes,
route provenance, type conversions, adjacency details,
input/snapshot hashes, and network counts log at DEBUG. Node messages include actual
`position`, separate `locator_position`, `donor`, and `coordinate_source`
(`donor_spline`, `locator`, or `port_relocation`). Input hashes also remain internal bookkeeping for
source-change verification before output replacement. Validation and export
summaries log at INFO for complete output and WARNING for drafts.

`complete` means all required static checks could run and none failed. `draft`
means emitted output has a violation, implementation limitation, or unverified
required check. Fatal input/schema/output-integrity failures prevent replacement.
CLI exit codes remain 0, 3 and 1 respectively, regardless of logging settings.
Neither status proves playability. Geography caches stay outside playable content.

`build_geography(..., sample_points=...)` samples requested world coordinates into
`Geography.province_samples`, keyed by raster pixel. `province_at(x, z)` is a pure
lookup: x maps to `floor(x)`, y to `floor(height - z)`, with horizontal wrapping
only when configured. Points without either a sample or province-span evidence
return `None`, as do out-of-range points. The
filesystem pipeline requests land-port donor and float32 final port-locator samples;
boundary caches do not cache these samples. `sea_provinces`, `lake_provinces`, and
`coastal_provinces` distinguish shared sea edges from lake edges or corner contact.
`build_geography` sets `placement_available`; manually constructed geography must
set it alongside its samples and classifications to enable placement checks.
Direct callers without placement data still preserve donor coordinates, but port
checks report `port_validation_unavailable` and keep the result a draft.

`Geography.required` records mandatory non-strait state pairs; `straits` records
permitted optional crossings. Initialization normalizes legacy manual `required`
entries with `kind: sea` or `strait` into `straits`, without editing caller-owned
containers. Mixed evidence retains its required non-strait border.
`land_connections_required(state)` returns `True`, `False`, or `None`, based on
known mandatory neighbors and missing adjacency evidence.

For manually constructed `Geography`, the supplied adjacency tables are authoritative
by default. Set `adjacency_available=False` when absent pairs cannot be determined;
`uncertain` records individual unresolved state pairs. `adjacent(a, b)` returns
`True` for either a required land border or a permitted strait, `False` for known
nonadjacency, and `None` for missing evidence. File-built geography records these
qualifications for unsupported crossings or incomplete border evidence. An independently known
passable border can establish adjacency despite an unknown alternative crossing.

Synthetic tests cover binary round trips, routing, geography, ports, failures,
repeatability and integration. Installed-game smoke tests are separate. Before
adopting an export, record editor inspection, error-log results, land/naval
movement and save/reload with the tested game/mod versions and input hashes.
