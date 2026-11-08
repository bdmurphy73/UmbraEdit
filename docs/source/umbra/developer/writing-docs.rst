# UmbraEdit Documentation Writing Standard

This document defines the writing standard for UmbraEdit documentation.
All feature pages must follow it.

## Voice and Tone

- Address the reader as **you**.
- Use **present tense**.
- One idea per paragraph.
- Headings name tasks ("Assign a speaker"), not concepts ("Speaker assignment").
- Be direct. No hedging.

## Formatting

- **Bold** for UI labels exactly as they appear in the interface.
- ``Literals`` for file names, keywords, values, and code.
- ``:kbd:`` for keyboard keys.
- ``:doc:`` for links to other manual pages.
- No "simply", "just", "obviously", or "of course".

## Examples

- Every example must be complete and runnable as shown.
- Use the ``umbra-example`` directive so the real parser verifies it.
- Every example must show the expected result.

## Images

- Every image must have alt text.
- Use ``umbra-shot`` for screenshots.
- No screenshot of text that could be a code block.

## Terminology

- Every term is defined once in the glossary.
- Link to the glossary entry on first use.
- Do not invent synonyms for defined terms.

## Page Structure

Every feature page follows the template in
``docs/source/_templates/feature_page.rst.tpl``:

1. Overview (What it is, What it does, Why it exists)
2. Before you start
3. Quick start
4. Tasks
5. Concepts
6. Reference
7. Examples
8. Messages and checks
9. Troubleshooting
10. FAQ
11. See also

A section that does not apply says so in one line: *"This section does
not apply to this feature."* It is not deleted.
