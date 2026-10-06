from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from metadata_automation.cli import main
from metadata_automation.metadata import (
    PLATFORMS, ValidationError, extract, generate, schema, validate,
)


def brief():
    return {"language": "en", "title": "Public budgets", "summary": "Read revenue and spending.",
            "keywords": ["public budget", "Reform", "reform", "ბიუჯეტი", "!!!"],
            "links": [{"label": "Notes", "url": "https://example.org/notes?year=2026#sources"}],
            "chapters": [{"time": "00:00", "title": "Totals"},
                         {"time": "01:00", "title": "Questions"}]}


class MetadataTests(unittest.TestCase):
    def test_all_platforms_schema_and_canonical_determinism(self):
        value = brief()
        first = generate(value)
        second = generate(dict(reversed(list(value.items()))))
        self.assertEqual(first, second)
        self.assertEqual(tuple(first["platforms"]), PLATFORMS)
        self.assertEqual(set(first["source"]), {"language", "title", "brief_sha256"})
        for kind in ("brief", "metadata"):
            Draft202012Validator.check_schema(schema(kind))
        Draft202012Validator(schema()).validate(first)
        self.assertIn("00:00 Totals\n01:00 Questions", first["platforms"]["youtube"]["description"])
        self.assertEqual(first["platforms"]["youtube"]["tags"],
                         ["public budget", "Reform", "ბიუჯეტი", "!!!"])
        self.assertEqual(first["platforms"]["instagram"]["hashtags"],
                         ["#publicbudget", "#Reform", "#ბიუჯეტი"])
        self.assertIn("https://example.org/notes?year=2026#sources", first["platforms"]["x"]["text"])

    def test_long_text_and_transcript_provenance(self):
        value = brief()
        value["summary"] = "💡" * 20000 + "\r\nExact facts."
        value["transcript"] = "Private editorial context."
        result = generate(value)
        self.assertIn("💡" * 20000 + "\nExact facts.", result["platforms"]["tiktok"]["caption"])
        self.assertNotIn("Private editorial context.", json.dumps(result))
        other = deepcopy(value)
        other["transcript"] += " Updated."
        self.assertNotEqual(result["source"]["brief_sha256"], generate(other)["source"]["brief_sha256"])

    def test_overrides_and_no_duplicate_hashtag_append(self):
        value = brief()
        value["platforms"] = {"youtube": {"title": "Reviewed title", "tags": []},
                              "instagram": {"caption": "A custom\ncaption #Exact", "hashtags": ["#Exact", "#More"]},
                              "x": {"text": "Short draft", "hashtags": []}}
        result = generate(value)
        self.assertEqual(result["platforms"]["youtube"]["title"], "Reviewed title")
        self.assertEqual(result["platforms"]["youtube"]["tags"], [])
        self.assertEqual(result["platforms"]["instagram"]["caption"], "A custom\ncaption #Exact\n\n#More")
        self.assertEqual(result["platforms"]["x"], {"text": "Short draft", "hashtags": []})

    def test_legacy_import_ignores_extras_and_extract_is_flat(self):
        legacy = {"title": "Reviewed", "description": "Exact\nwhitespace\n", "tags": ["one", "two"],
                  "timestamps": ["00:00"], "category": "policy", "type": "essay",
                  "level": 2, "problems": ["draft"], "account": "ignored"}
        result = generate(brief(), legacy)
        expected = {name: legacy[name] for name in ("title", "description", "tags")}
        self.assertEqual(extract(result, "youtube"), expected)
        self.assertIn("youtube_metadata_sha256", result["source"])
        self.assertNotIn("account", json.dumps(result))
        self.assertEqual(generate(brief(), expected), result)
        self.assertEqual(result["platforms"]["vimeo"]["title"], "Public budgets")
        legacy["title"] = " "
        with self.assertRaises(ValidationError):
            generate(brief(), legacy)

    def test_hashtag_casing_boundaries_duplicates_and_url_fragments(self):
        value = {"language": "en", "title": "AI", "summary": "Topic #ai. Link https://example.org/#AI", "keywords": ["AI"]}
        result = generate(value)
        self.assertEqual(result["platforms"]["x"]["hashtags"], ["#ai"])
        self.assertEqual(result["platforms"]["x"]["text"], value["summary"])
        value["summary"] = "Only https://example.org/#AI and #AIsystems"
        self.assertTrue(generate(value)["platforms"]["x"]["text"].endswith("\n\n#AI"))
        for scheme in ("HTTPS", "hTtPs", "HTTP", "hTtP"):
            with self.subTest(scheme=scheme):
                value["summary"] = f"Facts {scheme}://example.org/#AI"
                result = generate(value)
                self.assertEqual(result["platforms"]["x"]["text"], value["summary"] + "\n\n#AI")
                self.assertEqual(result["platforms"]["x"]["hashtags"], ["#AI"])
                validate(result)
        value["summary"] = "Repeated #ai and #AI"
        with self.assertRaises(ValidationError):
            generate(value)

    def test_ambiguous_youtube_override_rejected(self):
        value = brief()
        value["platforms"] = {"youtube": {"title": "Override"}}
        with self.assertRaises(ValidationError):
            generate(value, {"title": "Legacy", "description": "", "tags": []})

    def test_invalid_briefs(self):
        changes = [
            {"title": " "}, {"title": "Two\nlines"}, {"summary": "\u0000"},
            {"summary": "\ud800"}, {"privacy": "public"}, {"keywords": [3]},
            {"links": [{"label": "Link", "url": "javascript:alert(1)"}]},
            {"links": [{"label": "Link", "url": "https://user:secret@example.org/"}]},
            {"links": [{"label": "Link", "url": "https://example.org:wrong/"}]},
            {"chapters": [{"time": "00:01", "title": "One"}, {"time": "00:00", "title": "Zero"}]},
            {"platforms": {"unknown": {"text": "Draft"}}},
            {"platforms": {"tiktok": {"caption": "Draft", "hashtags": ["#bad-tag"]}}},
        ]
        for change in changes:
            with self.subTest(change=ascii(change)):
                value = brief()
                value.update(change)
                with self.assertRaises(ValidationError):
                    generate(value)

    def test_invalid_metadata_schema_version_unknown_fields_and_hashtag_presence(self):
        value = generate(brief())
        mutations = [lambda result: result.update(schema_version="2.0.0"),
                     lambda result: result.update(media="video.mp4"),
                     lambda result: result["platforms"].pop("vk"),
                     lambda result: result["platforms"]["instagram"].update(caption="Missing hashtags"),
                     lambda result: result["platforms"]["youtube"].update(tags=["one", "ONE"])]
        for mutate in mutations:
            changed = deepcopy(value)
            mutate(changed)
            with self.assertRaises(ValidationError):
                validate(changed)


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "metadata_automation", *map(str, arguments)],
                              capture_output=True, text=True, check=False)

    def test_generate_validate_extract_and_schema_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, flat = root / "brief.json", root / "metadata.json", root / "youtube.json"
            source.write_text(json.dumps(brief()), encoding="utf-8")
            self.assertEqual(self.run_cli("generate", source, "-o", output).returncode, 0)
            self.assertEqual(self.run_cli("validate", output).returncode, 0)
            self.assertEqual(self.run_cli("validate", source, "--kind", "brief").returncode, 0)
            self.assertEqual(self.run_cli("extract", "youtube", output, "-o", flat).returncode, 0)
            self.assertEqual(set(json.loads(flat.read_text())), {"title", "description", "tags"})
            exported = self.run_cli("schema")
            self.assertEqual(exported.returncode, 0)
            self.assertEqual(json.loads(exported.stdout), schema())
            self.assertEqual(self.run_cli("generate", source).stdout, output.read_text())
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({"title": "Legacy", "description": "", "tags": [], "timestamps": []}))
            imported = self.run_cli("generate", source, "--youtube-metadata", legacy)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertEqual(json.loads(imported.stdout)["platforms"]["youtube"]["title"], "Legacy")

    def test_invalid_input_exit_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "brief.json", Path(directory) / "existing.json"
            output.write_text("preserved")
            for bad_json in ('{"title":"a","title":"b"}', '{"summary":NaN}', '{"summary":Infinity}', '{}', '{'):
                source.write_text(bad_json)
                result = self.run_cli("generate", source, "-o", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(output.read_text(), "preserved")

    def test_stdin_stdout_and_single_stdin_input_rule(self):
        with patch("sys.stdin", io.StringIO(json.dumps(brief()))), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["generate", "-"]), 0)
            validate(json.loads(output.getvalue()))
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(main(["generate", "-", "--youtube-metadata", "-"]), 2)


if __name__ == "__main__":
    unittest.main()
