"""Local schema validation and deterministic, fact-preserving transformations."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json
import re
import unicodedata
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "1.0.0"
SCHEMA_VERSIONS = (SCHEMA_VERSION, "2.0.0")
PLATFORMS = (
    "youtube", "facebook", "instagram", "tiktok", "x", "threads",
    "linkedin", "vimeo", "vk",
)
V2_PLATFORMS = (*PLATFORMS, "pinterest")
VIDEO_PLATFORMS = frozenset(("youtube", "vimeo", "vk"))
CAPTION_PLATFORMS = frozenset(("facebook", "instagram", "tiktok"))


class ValidationError(ValueError):
    """An input cannot be represented by the published metadata contract."""


def _check_schema_version(schema_version: str) -> None:
    if schema_version not in SCHEMA_VERSIONS:
        raise ValidationError(f"Unsupported schema version: {schema_version}")


@lru_cache(maxsize=4)
def schema(kind: str = "metadata", schema_version: str = SCHEMA_VERSION) -> dict:
    if kind not in ("brief", "metadata"):
        raise ValidationError(f"Unknown document kind: {kind}")
    _check_schema_version(schema_version)
    suffix = ".v2" if schema_version == "2.0.0" else ""
    resource = files("metadata_automation").joinpath("schemas", f"{kind}{suffix}.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _validator(kind: str, schema_version: str) -> Draft202012Validator:
    document = schema(kind, schema_version)
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def _check_schema(value: object, validator: Draft202012Validator) -> None:
    error = next(validator.iter_errors(value), None)
    if error is not None:
        location = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}"
                                  for part in error.absolute_path)
        raise ValidationError(f"{location}: {error.message}")


def _check_strings(value: object, location: str = "$") -> None:
    if isinstance(value, str):
        if any(unicodedata.category(char) == "Cs" or
               (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
               for char in value):
            raise ValidationError(f"{location}: unsupported control character or Unicode surrogate")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_strings(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_strings(item, f"{location}.{key}")


def _text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _single_line(value: str, location: str) -> None:
    if not value.strip() or any(char in value for char in "\n\r\t"):
        raise ValidationError(f"{location}: expected nonempty single-line text")


def _tag_char(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in "LNM"


def _hashtag_matches(text: str, hashtag: str) -> list[str]:
    """Find whole Unicode hashtag tokens, excluding HTTP(S) URL fragments."""
    urls = [(match.start(), match.end()) for match in re.finditer(r"https?://\S+", text, re.IGNORECASE)]
    matches = []
    for match in re.finditer("#", text):
        index = match.start()
        if any(start <= index < end for start, end in urls):
            continue
        if index and (_tag_char(text[index - 1]) or text[index - 1] == "#"):
            continue
        end = index + 1
        while end < len(text) and _tag_char(text[end]):
            end += 1
        token = text[index:end]
        if token.casefold() == hashtag.casefold():
            matches.append(token)
    return matches


def _check_block(block: dict, platform: str, *, complete: bool) -> None:
    location = f"$.platforms.{platform}"
    if platform in VIDEO_PLATFORMS:
        if "title" in block:
            _single_line(block["title"], location + ".title")
        if "tags" in block:
            for index, tag in enumerate(block["tags"]):
                _single_line(tag, f"{location}.tags[{index}]")
            if complete and len({tag.casefold() for tag in block["tags"]}) != len(block["tags"]):
                raise ValidationError(f"{location}.tags: duplicate tags")
    else:
        if platform == "pinterest" and "title" in block:
            _single_line(block["title"], location + ".title")
        field = ("description" if platform == "pinterest" else
                 "caption" if platform in CAPTION_PLATFORMS else "text")
        if field in block and not block[field].strip():
            raise ValidationError(f"{location}.{field}: expected nonempty text")
        hashtags = block.get("hashtags", [])
        for index, hashtag in enumerate(hashtags):
            if not hashtag.startswith("#") or len(hashtag) < 2 or not all(
                _tag_char(char) for char in hashtag[1:]
            ):
                raise ValidationError(f"{location}.hashtags[{index}]: expected # followed by Unicode letters, numbers, marks or underscores")
            if complete and len(_hashtag_matches(block[field], hashtag)) != 1:
                raise ValidationError(f"{location}.hashtags[{index}]: hashtag must occur exactly once in {field}, outside URLs")
        if complete and len({tag.casefold() for tag in hashtags}) != len(hashtags):
            raise ValidationError(f"{location}.hashtags: duplicate hashtags")


def validate(value: object, kind: str = "metadata", *, schema_version: str | None = None) -> None:
    """Check the bundled Draft 2020-12 schema, then semantic text invariants."""
    if kind == "metadata" and schema_version is None and isinstance(value, dict):
        schema_version = value.get("schema_version", SCHEMA_VERSION)
    schema_version = SCHEMA_VERSION if schema_version is None else schema_version
    _check_schema_version(schema_version)
    _check_schema(value, _validator(kind, schema_version))
    _check_strings(value)
    assert isinstance(value, dict)
    if kind == "brief":
        for name in ("language", "title"):
            _single_line(value[name], f"$.{name}")
        if not value["summary"].strip():
            raise ValidationError("$.summary: expected nonempty text")
        if "transcript" in value and not value["transcript"].strip():
            raise ValidationError("$.transcript: expected nonempty text")
        for index, keyword in enumerate(value.get("keywords", [])):
            _single_line(keyword, f"$.keywords[{index}]")
        previous = -1
        for index, chapter in enumerate(value.get("chapters", [])):
            _single_line(chapter["title"], f"$.chapters[{index}].title")
            seconds = 0
            for part in chapter["time"].split(":"):
                seconds = seconds * 60 + int(part)
            if seconds <= previous:
                raise ValidationError(f"$.chapters[{index}].time: chapters must be in strictly increasing order")
            previous = seconds
        for index, link in enumerate(value.get("links", [])):
            _single_line(link["label"], f"$.links[{index}].label")
            url = link["url"]
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
                valid = valid and parsed.username is None and parsed.password is None
                parsed.port  # Validate a supplied port as well.
            except ValueError:
                valid = False
            if not valid or any(char.isspace() for char in url):
                raise ValidationError(f"$.links[{index}].url: expected an absolute HTTP(S) URL without credentials or whitespace")
        for platform, block in value.get("platforms", {}).items():
            _check_block(block, platform, complete=False)
    else:
        _single_line(value["source"]["language"], "$.source.language")
        _single_line(value["source"]["title"], "$.source.title")
        for platform, block in value["platforms"].items():
            _check_block(block, platform, complete=True)


def validate_youtube(value: object) -> None:
    """Validate a legacy flat YouTube publication document, with no code import."""
    document = schema()
    video_schema = {"$schema": document["$schema"], "$defs": document["$defs"],
                    "$ref": "#/$defs/video"}
    publication = _youtube_fields(value)
    _check_schema(publication, Draft202012Validator(video_schema))
    _check_strings(publication)
    _check_block(publication, "youtube", complete=True)


def _youtube_fields(value: object) -> object:
    if not isinstance(value, dict):
        return value
    return {key: value[key] for key in ("title", "description", "tags") if key in value}


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = _text(value)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _digest(value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _join(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _hashtags(keywords: list[str]) -> list[str]:
    values = []
    for keyword in keywords:
        token = "".join(char for char in unicodedata.normalize("NFC", keyword) if _tag_char(char))
        if token:
            values.append("#" + token)
    return _unique(values)


def _append_hashtags(text: str, hashtags: list[str]) -> str:
    missing = [tag for tag in hashtags if not _hashtag_matches(text, tag)]
    return _join([text, " ".join(missing)])


def generate(brief: dict, youtube_metadata: dict | None = None, *,
             schema_version: str = SCHEMA_VERSION) -> dict:
    """Derive drafts from the supplied editorial facts, without external I/O."""
    validate(brief, "brief", schema_version=schema_version)
    if youtube_metadata is not None:
        validate_youtube(youtube_metadata)
        if "youtube" in brief.get("platforms", {}):
            raise ValidationError("Choose either $.platforms.youtube or --youtube-metadata, not both")
    title, summary = _text(brief["title"]), _text(brief["summary"])
    keywords = _unique(brief.get("keywords", []))
    hashtags = _hashtags(keywords)
    chapters = "\n".join(f"{chapter['time']} {_text(chapter['title'])}"
                         for chapter in brief.get("chapters", []))
    links = "\n".join(f"{_text(link['label'])}: {link['url']}"
                      for link in brief.get("links", []))
    description = _join([summary, chapters, links])
    caption = _join([title if title != summary else "", summary, links])
    short_text = _join([summary, links])
    source = {"language": _text(brief["language"]), "title": title,
              "brief_sha256": _digest(brief)}
    if youtube_metadata is not None:
        source["youtube_metadata_sha256"] = _digest(_youtube_fields(youtube_metadata))
    platforms = {}
    for platform in V2_PLATFORMS if schema_version == "2.0.0" else PLATFORMS:
        override = brief.get("platforms", {}).get(platform, {})
        if platform in VIDEO_PLATFORMS:
            block = {"title": _text(override.get("title", title)),
                     "description": _text(override.get("description", description)),
                     "tags": _unique(override.get("tags", keywords))}
            if platform == "youtube" and youtube_metadata is not None:
                block = deepcopy(_youtube_fields(youtube_metadata))
        else:
            field = ("description" if platform == "pinterest" else
                     "caption" if platform in CAPTION_PLATFORMS else "text")
            base = short_text if platform in ("x", "threads", "pinterest") else caption
            body = _text(override.get(field, base))
            tokens = _unique(override.get("hashtags", hashtags))
            # Preserve an existing token's spelling while avoiding another casing.
            tokens = [matches[0] if (matches := _hashtag_matches(body, tag)) else tag for tag in tokens]
            block = {field: _append_hashtags(body, tokens),
                     "hashtags": tokens}
            if platform == "pinterest":
                block = {"title": _text(override.get("title", title)), **block}
        platforms[platform] = block
    result = {"schema_version": schema_version, "source": source, "platforms": platforms}
    validate(result)
    return result


def extract(metadata: dict, platform: str) -> dict:
    validate(metadata)
    if platform not in V2_PLATFORMS:
        raise ValidationError(f"Unknown platform: {platform}")
    if platform == "pinterest" and metadata["schema_version"] != "2.0.0":
        raise ValidationError("Pinterest extraction requires schema version 2.0.0")
    return deepcopy(metadata["platforms"][platform])
