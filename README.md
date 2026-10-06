# metadata-automation

A Python 3.12 CLI that derives deterministic metadata drafts for one video from a supplied editorial JSON brief. By default it produces YouTube, Facebook, Instagram, TikTok, X, Threads, LinkedIn, Vimeo and VK blocks in a schema `1.0.0` envelope. Explicit schema `2.0.0` generation adds a required Pinterest block.

The brief supplies the facts and the language. This package does not infer a title or summary from bare media, transcribe a video, translate text, call an AI service, or publish to social networks. It has no network operations and uses no platform credentials. Its only runtime dependency is `jsonschema`, which validates the bundled Draft 2020-12 schemas locally.

## Install and run

With Python 3.12 or later and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked --python 3.12
uv run metadata-automation generate examples/brief.json -o metadata.json
uv run metadata-automation validate metadata.json
uv run metadata-automation extract youtube metadata.json -o youtube.json

# Include Pinterest in a ten-platform envelope.
uv run metadata-automation generate examples/brief.json --schema-version 2.0.0 -o metadata-v2.json
uv run metadata-automation extract pinterest metadata-v2.json -o pinterest.json
```

Alternatively, install the package with `python -m pip install .` and run `metadata-automation` directly. `python -m metadata_automation` exposes the same commands. `--version` reads the package version from the native manifest/installed package metadata.

## Commands

| Command | Result |
| --- | --- |
| `generate BRIEF [--schema-version 1.0.0\|2.0.0] [-o OUTPUT]` | Validate the selected brief schema, derive all required blocks, validate and write the envelope. Default: `1.0.0` with nine platforms; `2.0.0` adds Pinterest. |
| `generate BRIEF --youtube-metadata LEGACY [-o OUTPUT]` | Import only the legacy document's `title`, `description`, `tags` into the YouTube block; generate other blocks from the brief. |
| `validate INPUT [--kind brief\|metadata] [--schema-version 1.0.0\|2.0.0]` | Check the published schema and semantic invariants. Metadata selects its schema from `schema_version`; an explicit version must match. Brief validation defaults to `1.0.0`. Default kind: `metadata`. |
| `schema [--kind brief\|metadata] [--schema-version 1.0.0\|2.0.0] [-o OUTPUT]` | Export a bundled, self-contained Draft 2020-12 schema. Default kind: `metadata`; default version: `1.0.0`. |
| `extract PLATFORM METADATA [-o OUTPUT]` | Validate the whole envelope and export exactly one platform block. |

Use `-` in place of an input path for stdin. Output defaults to stdout; `-o -` also selects stdout. JSON output is UTF-8, indented with two spaces and terminated by one newline. Validation messages and errors go to stderr. Exit status is `0` for success and `2` for invalid input or file errors. Named outputs are replaced atomically only after validation succeeds. Input and output may be the same path; an invalid document never replaces the existing output.

## Brief

[examples/brief.json](examples/brief.json) shows all editorial fields except the optional `transcript`. The required fields are:

```json
{
  "language": "en",
  "title": "How to read a public budget",
  "summary": "Compare revenue, spending and changes from last year."
}
```

Optional fields:

- `keywords`: ordered strings used as video tags and to derive hashtags. Tags are trimmed and deduplicated case insensitively while retaining first spelling/order. Hashtags remove spaces and punctuation from NFC-normalized keywords and retain Unicode letters, numbers, combining marks and underscores. Keywords that contain no such characters produce no hashtag.
- `transcript`: supplied context accepted into the brief fingerprint. The deterministic formatter does not mine or copy transcript text into output. Supply the editorial summary and keywords you want published.
- `chapters`: ordered `{ "time": "00:00", "title": "Introduction" }` entries. Use `MM:SS` or `HH:MM:SS` and strictly increasing times. These appear in video descriptions. The package does not verify video duration or promise that a platform recognizes them as interactive chapters.
- `links`: ordered `{ "label": "Notes", "url": "https://example.org/notes" }` entries. Links appear in every generated description/caption/text. Absolute HTTP(S) URLs without embedded credentials or whitespace are accepted and preserved without fetching or shortening them.
- `platforms`: optional partial overrides using the target block's fields. Video platforms accept `title`, `description`, `tags`; Facebook/Instagram/TikTok accept `caption`, `hashtags`; X/Threads/LinkedIn accept `text`, `hashtags`. With schema `2.0.0`, Pinterest accepts `title`, `description`, `hashtags`. An empty override object is rejected. Overriding `tags` or `hashtags` with `[]` clears them. Missing fields retain generated defaults. Explicit descriptions replace the generated body and links as well. A Pinterest override requires `generate --schema-version 2.0.0`; the default v1 command rejects it rather than dropping it.

Summary and multiline override whitespace is preserved internally; outer whitespace and CRLF/CR line endings are normalized. Titles, language, keywords, chapter titles and link labels must be nonempty single-line text. Unknown fields, invalid types, duplicate JSON keys, nonfinite JSON numbers, control characters and unpaired Unicode surrogates are rejected. Media paths, account, privacy and request ID do not belong in the brief or envelope; pass them explicitly to the publisher.

## Envelope and publisher contract

Supported schema versions are `1.0.0` and `2.0.0`, independent of package version `0.2.0`. `generate` and `schema` retain `1.0.0` as their default. The original v1 schema files and nine-platform contract are unchanged. Every envelope has exactly `schema_version`, `source` and `platforms`; v2 requires all ten blocks, including Pinterest. Unknown schema versions are rejected.

`source` contains `language`, `title` and `brief_sha256`. The digest is SHA-256 over the validated input brief serialized as compact JSON with sorted object keys, UTF-8 Unicode and no ASCII escaping. Input indentation and object key order do not affect it; editorial strings and optional fields do. The brief, transcript and links are not copied into provenance. A legacy import adds `youtube_metadata_sha256`, calculated over only its three consumed publication fields using the same canonical serialization.

| Platforms | Exact block fields |
| --- | --- |
| `youtube`, `vimeo`, `vk` | `title`, `description`, `tags` |
| `facebook`, `instagram`, `tiktok` | `caption`, `hashtags` |
| `x`, `threads`, `linkedin` | `text`, `hashtags` |
| `pinterest` (schema `2.0.0` only) | `title`, `description`, `hashtags` |

Video descriptions contain the summary, chapters and links separated by blank lines. Captions and LinkedIn text contain the title, summary and links; X and Threads text use the summary and links. Pinterest uses the brief title and a description containing the summary and links, followed by hashtags. Hashtags form a final line. A supplied caption/text/Pinterest description override becomes the body; configured hashtags absent from it are appended once.

**`caption`, `text` and Pinterest `description` are authoritative complete drafts, including hashtags.** `hashtags` contains the tokens used (including their leading `#`) for inspection. Publishers must not append that array to the text again. Existing tokens are matched case insensitively and retain their spelling; URL fragments are excluded. Validation requires every listed token to occur exactly once as a complete hashtag outside URLs. Repeated configured tokens in supplied text are rejected so the formatter never has to discard editorial content. No publishing limits are encoded: long supplied titles, text, links and tag lists are preserved without silent truncation. The publisher must check constraints for its actual API or browser transport and allow editorial review before publication. Use a partial Pinterest override for reviewed publication text when needed.

All original nine platforms can be extracted from either supported envelope version. `extract pinterest` requires a validated v2 envelope and returns exactly `{ "title": "...", "description": "...", "hashtags": [...] }`.

```sh
uv run metadata-automation extract youtube metadata.json -o youtube.json
```

This writes a flat `{ "title": "...", "description": "...", "tags": [...] }` document compatible with the existing `youtube-automation-prepare/metadata.py` consumer. It does not import or run the legacy generator, its hardcoded blog lookup, or Whisper.

To reuse an existing legacy generator document explicitly:

```sh
uv run metadata-automation generate examples/brief.json \
  --youtube-metadata examples/youtube-metadata.json -o metadata.json
```

Legacy `timestamps`, `category`, `type`, `level`, `problems` and other extra fields are ignored. Its three publication fields must pass the strict video-block schema, including a nonempty title. They are preserved exactly. A simultaneous `platforms.youtube` brief override is rejected because it would make precedence ambiguous.

Published schemas are tracked and included in the installed package:

- [metadata.schema.json](src/metadata_automation/schemas/metadata.schema.json)
- [brief.schema.json](src/metadata_automation/schemas/brief.schema.json)
- [metadata.v2.schema.json](src/metadata_automation/schemas/metadata.v2.schema.json)
- [brief.v2.schema.json](src/metadata_automation/schemas/brief.v2.schema.json)

They have URN identifiers and only local `$ref` values; submitted documents cannot supply schema references or cause remote resolution. Schema validation covers document structure; local semantic validation additionally covers whitespace/control characters, valid link hosts/ports, chronological chapters, Unicode hashtag bodies, case insensitive duplicate output tags, and hashtag presence in final text. Consumers should pin their supported schema versions and validate locally.

## Verification

```sh
uv run --locked python -m unittest discover -s tests -v
```

Tests cover deterministic canonical fingerprints, v1 compatibility and v2 Pinterest generation, all platform blocks, Unicode/long text, partial overrides, complete descriptions and hashtag invariants, legacy extras and extraction, bundled schema validation, unknown versions, CLI round trips and safe output handling.
