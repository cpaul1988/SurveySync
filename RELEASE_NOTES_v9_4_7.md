# SurveySync 9.4.7-beta.1 — ControlSync reshoot round trip

From a failed three-shot Control QC result, issue a project-bound crew packet with the next available shot IDs and field instructions. Stage a returned CSV, TXT, TSV, JOB, JXL or JobXML file, then inspect the before/after residuals and field QC. Staging preserves the original source and leaves the active control solution unchanged.

A reviewer can reject the return or approve it after the preview passes and includes a returned shot in the selected triplet. Approval checks that project observations, coordinate context and staged source have not changed, imports the three reserved shots, and reruns QC for the requested control alone. The downloadable approved ZIP carries the accepted coordinates, selected shots, source checksum and review record. The project audit and deliverables registry retain provenance.

This candidate is based on 9.4.6 Stable. Windows installer and representative field-data acceptance remain required before promotion.
