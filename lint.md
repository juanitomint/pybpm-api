# Lint Issues — Fixed List

All issues below were resolved. Final `make lint` passes cleanly.

- [x] **E501** Line too long in `services/bpm_model_service.py:262` (95 chars)
  - Wrapped list comprehension across multiple lines

- [x] **W293** Blank line contains whitespace in `services/auth_service.py:129`
  - Removed trailing whitespace from blank docstring line

- [x] **E501** Line too long in `tests/test_bpm_model_service_extended.py:71` (94 chars)
  - Shortened docstring to fit within 88-character limit

- [x] **E501** Line too long in `tests/test_repo.py:3` (98 chars) — initial docstring comment
  - Rewrote opening docstring block to be more concise

- [x] **E501** Line too long in `tests/test_repo.py:9` (96 chars) — Step 9 list item
  - Shortened the bullet point description

- [x] **E501** Line too long in `tests/test_repo.py:11` (94 chars) — "Each step validates…" line
  - Split into shorter phrasing within docstring

- [x] **E501** Line too long in `tests/test_repo.py:164` (95 chars) — test method docstring
  - Rewrote to be more concise: "Raise ResourceNotFoundError when the source id doesn't exist."

- [x] **E501** Line too long in `tests/test_schema.py:90` (96 chars) — assertion error message
  - Split f-string across multiple lines in assert statement
