> Historical v4 audit and subsequent v5 implementation: the 155 rows below describe the pre-supplement result. Version 5 now resolves 89 with strict MAR evidence and 10 with standard intersection class consensus, leaving 56. See [current delivery](DELIVERY.md).

# Exception review

Reviewed all 155 unresolved rows from the restored full v4 result against the frozen permit/LRS/roadway files. A separate current public MAR address-point and roadway lookup supplies additional evidence. The original v4 CSV is preserved. The evidence now also supports the separately versioned v5 result.

## Findings

| Evidence category | Rows | Interpretation |
| --- | --- | --- |
| ` AND ` intersection descriptions | 31 | 25 distinct addresses; all were flagged by the different-road 1 m near-tie rule |
| Exact active MAR address and unique eligible roadway key/class | 107 | 92 street-name conflicts, 9 other near ties and 6 no-road cases now have address-based candidates |
| Other cases requiring separate evidence | 17 | 13 block ranges, 3 exit/ramp descriptions and 1 MAR address without a usable unique key |

These groups are disjoint and account for all 155 rows. There are 142 distinct source addresses and 145 distinct source coordinate points.

## Intersection semantics

The user's proposed `street A AND street B` interpretation is confirmed in the source. Splitting these descriptions into two named arms explains many near ties. Within the saved closest-distance-plus-1 m candidate set, 13 of the 31 intersection rows have one shared valid FHWA class and 18 have differing classes. Of the 13, ten also have both address arms parsed and represented among those candidates. Four of the 31 descriptions have special boundary-street, missing-quadrant or directional-ramp forms and need separate handling.

Examples:

- OBJECTID 1013884: HOLBROOK STREET NE AND MORSE STREET NE; all near candidates are FHWA 7.
- OBJECTID 1019993: FOXHALL ROAD NW AND CANAL ROAD NW; all near candidates are FHWA 3.
- OBJECTID 1040420: BLADENSBURG ROAD NE AND MOUNT OLIVET ROAD NE; all near candidates are FHWA 4.
- OBJECTID 1015586: 1ST STREET SE AND INDEPENDENCE AVENUE SE; near candidates contain FHWA 3, 5 and 7. Selecting the highest class would add an unestablished work-road assumption.

A shared class can support a separately versioned class-consensus outcome without inventing a unique subblock. It does not by itself certify every road association. Different-class intersections remain unresolved until intended-road evidence or an explicitly documented multi-road scope is established. Treating the first named street as the work road, choosing the nearest key arbitrarily, or taking the highest road class are not supported by the address string alone.

## MAR cross-check

The public [MAR Address Points layer](https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Location_WebMercator/FeatureServer/0) was queried for 108 unique non-intersection, non-block-range addresses using exact uppercase/whitespace-normalized address text. Responses, geometry and query parameters were retained. The service describes these address points as typically placed on buildings. They supply address-to-road-reference evidence; they do not independently identify where the permitted work occurs.

For 107 source rows there is an exact ACTIVE address with one nonempty subblock key, one returned eligible roadway record and a valid FHWA class. The referenced road name agrees with the source address's normalized street in all 107 cases. Of these, 89 keys are also present in the frozen eligible candidates within 50 m. The other 18 require explicit review of the source point/road relationship rather than silently widening the current radius. Ninety-six keys were present somewhere in the frozen road lookup, and all 96 retain the same FHWA class in the current service. These later lookups must be recorded separately from the frozen capture.

Examples: OBJECTID 1005867 names MINNESOTA AVENUE SE while the nearest road is S ST SE; MAR references MINNESOTA AVE SE (FHWA 4), approximately 36 m from the permit point. OBJECTID 999231 names GEORGIA AVENUE NW while the nearest road is MORTON ST NW; MAR references GEORGIA AVE NW (FHWA 3), approximately 51 m from the permit point, outside the present radius. Distances to current roadway geometry are local geographic approximations used for screening, not replacements for saved LRS offsets.

## Additional checks

All 93 street-conflict addresses and their nearest unit-block strings parsed successfully. The nearest route name agreed with its own unit-block street in all 93; no definite parser defect was found. Eighty have a same-street candidate within 50 m, but each is more than 1 m farther than the nearest road. The same-street road has a higher class in 37 cases, the same class in 38 and a lower class in 5. A preference for the higher class would therefore introduce bias.

Among the 14 no-eligible-road cases, four have empty candidate lists and ten only have excluded Alley/Driveway/Unknown types. Some named streets are labelled Alley in the source; a street-like name does not establish eligibility. OBJECTID 1030385 has `MAR LOOKUP FAILED` in the nearest LRS unitBlock field, so that exception reflects missing source address evidence rather than a demonstrated road-name mismatch.

## Outputs and next action

Detailed local evidence is excluded from Git under `artifacts/reviews/exception_audit_20261015/`:

- `exception_review.csv`: one review row for each of the 155 exceptions.
- `intersection_review.csv`: all 31 intersection cases.
- `mar_supported_candidates.csv`: all 107 MAR-supported road candidates.
- `other_remaining.csv`: the other 17 cases.
- `case_evidence.json`, `raw/`, `summary.json`: candidate facts, retrieved responses and measured summary.
- `offline_summary.csv/json`: independent checks of the frozen inputs.

The original v4 result remains preserved at 4,828 matched and 155 unresolved. Version 5 implements the conservative intersection and MAR methods with independent verification, explicit supporting-key columns and a new result/package. Only 89 of the 107 MAR candidates pass the frozen 50 m and identity/class requirements; only ten standard intersections pass the strict two-arm checks.

The full CSV SHA-256 remains `35781106b1fa6e09e3090bbc8b403e3d0635ad827f77e356ef94f6f01040f4ed`.
