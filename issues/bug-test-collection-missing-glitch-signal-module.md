# Bug: `pytest` fails during test collection with `ModuleNotFoundError: glitch_signal`

## Summary
Running the test suite from a clean checkout fails at collection time because `glitch_signal` cannot be imported.

## Reproduction
1. Fresh clone of the repository.
2. Install test dependencies (for example, `pip install -e .[dev]`).
3. Run:
   ```bash
   pytest -q
   ```

## Actual result
Pytest aborts during collection with:

```text
ImportError while importing test module '/workspace/glitch-grow-ai-social-media-agent/tests/test_filename_parser.py'
...
E   ModuleNotFoundError: No module named 'glitch_signal'
```

## Expected result
`pytest` should collect tests successfully without import errors.

## Notes
- This blocks test execution before assertions run.
- Error observed on April 23, 2026 (UTC).
