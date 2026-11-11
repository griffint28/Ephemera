# Test fixtures

`synthetic_sso_omm.json` is an **invented** element set in CelesTrak's GP (OMM JSON) format.
It describes a circular, sun-synchronous orbit at 705 km and 98.2 degrees inclination, the
nominal orbit Landsat 8 flies, but it is not Landsat 8's real elements and its positions are not
real. It carries NORAD id 39084 only so that the tests can attach it to the configured L8 row.

Tests use it because they must run offline and must not depend on whatever CelesTrak returns
on a given day. Real element sets are fetched only by the `fetch-orbital-data` CLI command; the
check against Heavens-Above (`docs/verification.md`) uses those.
