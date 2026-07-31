# Adversarial fixture corpus

These fixtures are intentionally invalid or unsupported. They are tiny,
deterministic, inspectable, and safe to keep in Git. Tests copy them into a
temporary case root and never ask the application to modify this directory.

| Fixture | Purpose | Expected class of rejection |
| --- | --- | --- |
| `fake-signature.png` | Filename claims PNG while bytes are plain text | malformed/unsupported decoded content |
| `truncated.png` | Contains only a PNG signature and partial chunk marker | malformed image |
| `unsupported.pgm` | Valid one-pixel ASCII PGM image | unsupported format |
| `corrupt-mask.png` | Filename claims mask while bytes are invalid | corrupt mask/bundle hash or decode failure |
| `traversal-member-name.txt` | Archive-member traversal spelling | unsafe bundle path |
| `unknown-pipeline.json` | Stable unknown pipeline/version pair | unknown pipeline, with no fallback |

Oversized, symlink, FIFO/non-regular, hash-tampered, dimension-mismatched, and
incomplete-bundle cases are generated in temporary directories by pytest. That
keeps the repository small and permits boundary tests to derive values from the
active configured limits.
