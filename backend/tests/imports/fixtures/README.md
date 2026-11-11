# Import edge-case fixtures (SPEC §9 cases 17–29)

Each file name starts with the SPEC §9 case number it covers; assertions live in
`tests/api/test_import_pipeline.py`. Case 23 (same file twice), 27 (1,000,000
rows, generated on the fly) and 29 (worker crash mid-commit) need no static file.
