# Python assessment requirements

Checked against the supplied two-page **Python Test - CS12 Data Scientist** and two-page **Test Guidance CS12 Data Scientist**. This repository covers Python only, which the general guidance permits. The current full-data delivery is v5; see [package details and verification](DELIVERY.md).

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Occupancy layer 24 | Complete retained exact-filter cohort, reconciled source IDs/counts | Implemented and verified for capture |
| 2026 applied **or** issued permits | OR logic and Eastern-time year boundaries, with tests | Implemented; year-to-date scope stated |
| Construction Staging Area and Mobile Crane Work Zone | Exact filter and explicit counts: 4,983 / 0 | Implemented |
| DC Water, PEPCO, Washington Gas | 1,911 / 1,403 / 1,669 records; six documented aliases and broader identity audit | Implemented with stated coverage assumptions |
| One row per application location | 4,983 unique location rows, original fields/geometry preserved, whole-group checks | Verified |
| Location FHWA class, alleys excluded | Roadway lookup, original LRS evidence, strict MAR alternative, same-class intersection handling | 4,927 assigned; 56 explicitly unresolved |
| Highest class per application | Minimum valid FHWA code; certified highest blank for incomplete groups | 3,073 class-complete applications; 56 incomplete |
| Scripts and supporting files | Capture, MAR evidence capture, producer, independent verifier, tests, policy, raw evidence | Included in ZIP |
| Final CSV | Complete captured population retained, method/support keys and exceptions visible | Included; partial enrichment stated |
| README and configurable execution | Standalone commands, constants/assumptions and field dictionary | Included |
| Self-contained personal-name ZIP | Actual v5 Python ZIP and personal-name parent ZIP | Built and CRC/path checked |
| Windows 11 reproduction | Fresh path with spaces, new Python 3.11 environment, 59 tests, byte-identical full CSV regeneration | Passed for actual ZIP |
| Deliver the archive; GitHub supplementary | Verified Python ZIP committed under submission/; assessment destination not contacted | Final external submission remains |

## Completion decision

The project is ready to ship as an explicitly documented partial enrichment, as the instructions allow. It does **not** claim the full class-per-location target is achieved: 56 locations remain unresolved. Verification establishes source/policy consistency and reproduction, not independently surveyed road association or exhaustive recognition of all possible utility contractors.

The two enrichment approaches in the PDF are alternatives; implementing the MAR 2 geocoding API in addition to the available LRS/public MAR address-point route is not required. A GitHub link supplements the named ZIP and does not replace it. The parent archive contains the Python archive under a personal-name folder; no middle initial was supplied.

## Final action

Review the ZIP's README/REPORT and exception CSV, then submit `Yuhan_Wu_CS12_DataScientist_Tests.zip` from `deliverables/python_v5_readme_final` using the original supplied submission channel. Nothing has been sent there by this workflow. If time permits, obtain specific work-road evidence for remaining mixed-class intersections and out-of-radius addresses, then generate a separately verified revision.
