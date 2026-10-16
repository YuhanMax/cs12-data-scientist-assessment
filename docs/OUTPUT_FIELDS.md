# Output fields

The main CSV preserves all 113 source attribute columns, with their original names and values. JSON input snapshots preserve source nulls and geometry; CSV nulls are blank. Source dates remain epoch milliseconds. Added fields normally use `enrich_`; the tool chooses another prefix if a source column would collide.

| Added field | Meaning |
| --- | --- |
| `geometry_json`, `geometry_x/y` | Original query geometry, EPSG:4326; no relocation or snapping |
| `utility` | Utility mapped by the documented exact ApplicantCompany aliases |
| `match_status`, `match_reason` | Whether FHWA class is assigned under the policy, and the specific decision/error |
| `class_method` | `nearest_road`, `mar_address`, or `intersection_consensus`; blank when unresolved |
| `fhwa_code/name` | Assigned FHWA code 1–7 and label; blank when unresolved |
| `subblock_key`, `road_name/type`, `distance_m` | Chosen unique road for nearest/MAR outcomes. For unresolved rows these may be diagnostic only. Blank for intersection class consensus |
| `supporting_subblock_keys` | JSON list of supporting roadway keys; multiple keys are retained for class consensus |
| `evidence_reference` | `mar_evidence.json` for MAR, `frozen_lrs_and_roads` for intersection consensus; blank for baseline nearest-road decisions |
| `resolution_id/basis` | Historical exact-case identifier when applicable, and the documented decision basis |
| `candidate_count` | Raw count of eligible route-type candidates before the 50 m validity filter |
| `highest_known_code/name` | Minimum valid class across classified locations in this captured application; partial evidence for incomplete applications |
| `application_highest_code/name` | Requested application-wide highest class, populated only when application class coverage is complete |
| `application_locations`, `matched_locations` | Captured eligible locations and number with assigned FHWA classes |
| `application_complete` | Every captured eligible location has a class, no source MultiAddresses remain, and retained group-context checks find no omitted group location |

Code 1 is highest in the hierarchy and 7 is lowest. `matched` is a policy-derived class assignment, not field certification. `application_complete` describes class coverage of the defined captured application scope; it does not certify an independently surveyed location or a unique subblock at an intersection.

For a class-consensus intersection, every tied candidate must have the same class and both standard named address arms must be represented. Reporting that shared class does not assert a unique roadway. Different-class intersections remain unresolved; the tool does not choose the highest class merely to complete the row.

A MAR assignment may select a same-address road farther away than the geometric nearest road. It requires an exact ACTIVE MAR address, one referenced key, the original eligible LRS candidate within 50 m, matching street identities/types, and agreement between frozen/current FHWA class. The later MAR evidence is retained and hash-checked separately from the original permit capture. Address frontage remains an explicit approximation for permitted work-road association.

`REPORT.json` records scope, method counts, utility/type totals, exceptions and evidence provenance. `EXCEPTIONS.csv` contains all unresolved rows. Optional `resolved_changes.csv` in the delivered run records newly assigned locations against the earlier v4 result.
