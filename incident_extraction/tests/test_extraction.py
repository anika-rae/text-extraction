"""Offline checks. Mocked API calls do not demonstrate live model accuracy."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
from incident_extraction.extraction import ExtractionError, extract_incident, process_documents
from incident_extraction.prompts import FEW_SHOT_EXAMPLES
from incident_extraction.schemas import IncidentData


class SchemaTests(unittest.TestCase):
    def test_examples(self):
        for example in FEW_SHOT_EXAMPLES:
            with self.subTest(source=example["source"]):
                IncidentData.model_validate(example["result"])

    def test_invalid_fields(self):
        for values in [dict(date="2025-02-29"), dict(date="2025-1-01"),
                       dict(time="24:00"), dict(vehicle_count=True),
                       dict(vehicle_count="2"), dict(vehicle_count=0),
                       dict(time_approximate=True), dict(incident_type="unknown"),
                       dict(claimant_vehicle_id="vehicle_1"),
                       dict(impacts=[dict(target_region="roof")]),
                       dict(impacts=[dict(source_vehicle_id="vehicle_9")]),
                       dict(vehicles=[dict(id="vehicle_1"), dict(id="vehicle_1")]),
                       dict(extra="not allowed")]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                IncidentData.model_validate(values)

    def test_partial_information(self):
        result = IncidentData(vehicle_count=3, impacts=[{"target_region": "rear"}])
        self.assertIsNone(result.impacts[0].source_vehicle_id)
        self.assertEqual(result.vehicles, [])


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GROQ_API_KEY": "offline-test-placeholder"})
        self.env.start()
        self.groq = patch("incident_extraction.extraction.Groq")
        self.constructor = self.groq.start()
        self.client = self.constructor.return_value.__enter__.return_value
        self.create = self.client.chat.completions.create
        self.valid = json.dumps(FEW_SHOT_EXAMPLES[0]["result"])

    def tearDown(self):
        self.groq.stop()
        self.env.stop()

    def respond(self, content, reason="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=reason)])

    def test_success_one_request(self):
        self.create.return_value = self.respond(self.valid)
        self.assertEqual(extract_incident("A narrative").vehicle_count, 2)
        self.assertEqual(self.create.call_count, 1)
        kwargs = self.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_retry_invalid_json_and_schema(self):
        for invalid in ["not json", '{"vehicle_count": "2"}',
                        '{"date":null,"date":null}', '{"vehicle_count":NaN}']:
            with self.subTest(invalid=invalid):
                self.create.reset_mock()
                self.create.side_effect = [self.respond(invalid), self.respond(self.valid)]
                self.assertIsInstance(extract_incident("A narrative"), IncidentData)
                self.assertEqual(self.create.call_count, 2)
                self.assertIn("failed validation", self.create.call_args.kwargs["messages"][-1]["content"])

    def test_second_failure_and_empty_response(self):
        self.create.side_effect = [self.respond(None), self.respond("{}", "length")]
        with self.assertRaises(ExtractionError):
            extract_incident("A narrative")
        self.assertEqual(self.create.call_count, 2)

    def test_api_failure_does_not_retry(self):
        from groq import APIConnectionError
        import httpx
        self.create.side_effect = APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))
        with self.assertRaises(ExtractionError):
            extract_incident("A narrative")
        self.assertEqual(self.create.call_count, 1)

    def test_missing_key_and_empty_input(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with self.assertRaises(ExtractionError):
                extract_incident("A narrative")
        with self.assertRaises(ValueError):
            extract_incident(" ")
        self.create.assert_not_called()

    def test_save_independent_sources(self):
        self.create.return_value = self.respond(self.valid)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [dict(case_id="case_1", source=source, synthetic=True, text="A document")
                       for source in ["claimant", "police"]]
            path = root / "input.json"
            path.write_text(json.dumps(records))
            saved = process_documents(path, root / "outputs")
            self.assertEqual(len(saved), 2)
            for file, record in zip(saved, records):
                output = json.loads(file.read_text())
                self.assertEqual(output["source"], record["source"])
                self.assertEqual(output["case_id"], "case_1")
                IncidentData.model_validate(output["incident"])
            with self.assertRaises(ValueError):
                process_documents(path, root / "outputs")
            self.assertEqual(self.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
