# SurveySync v9.1.3 QA Report

## Scope

v9.1.3 is a focused FieldBookSync workflow patch implementing FBR-0010 and formalizing release documentation as a mandatory build gate. It preserves the v9.1.2 Field Note Profile Trainer and adds book-level profile assignment, representative-page preview, trainer handoff, profile persistence, and mixed-format precedence.

## Automated result

Final maintained combined suite: **183 passed, 0 failed**. Python compileall and JavaScript syntax checks also passed in the build environment. Windows GUI launchers were cross-built and verified as Windows GUI subsystem binaries.

## Automated coverage added

`tests/test_v913_fieldbook_training_workflow.py` verifies:

- assigning a field-note profile to one imported field book;
- persisted profile/version/mode metadata;
- book-level profile propagation to its pages;
- preservation of an independent page-specific override;
- effective precedence of page override over book default;
- returning a book to Auto mode;
- representative training-page selection and saved page IDs;
- profile-assignment API catalog output;
- FBR-0010 dashboard/trainer controls and API wiring.

Existing v9.1.2 tests continue to cover built-in BRT grammar, custom profile CRUD, privacy-preserving training hints, `.fnp` round trip, built-in profile overwrite protection, schema fields, and Trainer UI availability.

## Evidence / profile guardrails

Profile assignment does not create observations and does not overwrite raw OCR/vision evidence. Page overrides remain separate from the field-book default. Auto mode remains conservative. Built-in profile grammar is locked; training examples may reinforce its learned structural hints without mutating the canonical rules.

## Documentation gate

`scripts/validate_release_docs.py` verifies the current product version, required living documentation, current release notes/QA report, and `IMPLEMENTATION_INDEX.json`. `Build_SurveySync.ps1` invokes the documentation gate before compilation/tests.

## Feedback check

The FieldBook Sync Feedback Tracker was checked immediately before this build cycle. **FBR-0010** was the newest Intake item; no FBR-0011+ entry was present and the raw `Form Responses 1` sheet contained no unprocessed response rows.

## Environment limitations / field gates

Automated tests do not replace real Windows validation of handwriting/OCR behavior. Before Stable promotion:

1. Compile the Inno Setup installer on Windows.
2. Update an installed SurveySync 9.1.2 machine to 9.1.3.
3. Import the supplied BRT field book and verify the post-import profile panel.
4. Preview/train from representative pages and confirm project persistence after restart.
5. Validate at least one different field-note format and a mixed-format page override.
6. Run installed PaddleOCR/local vision smoke tests.
7. Exercise Point Range, Trimble JOB/JXL, Ron control reports, updater, and feedback submission.
