"""Colab-independent API extraction and saving of validated documents."""
import argparse
import json
import os
import re
from pathlib import Path

from groq import APIError, Groq
from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT
from .schemas import IncidentData

DEFAULT_MODEL = "llama-3.3-70b-versatile"


class ExtractionError(RuntimeError):
    """Extraction failed without producing a fabricated result."""


def _parse_response(content: str) -> IncidentData:
    # Standard json parsing rejects Markdown; reject non-standard numeric constants too.
    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    data = json.loads(content, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    return IncidentData.model_validate(data)


def extract_incident(text: str) -> IncidentData:
    """Extract one document; retry exactly once only for an invalid model response."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if not os.environ.get("GROQ_API_KEY"):
        raise ExtractionError("Set GROQ_API_KEY securely before running extraction.")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    # Disable SDK retries so request counts and API failures remain predictable.
    with Groq(max_retries=0, timeout=60.0) as client:
        for attempt in range(2):
            try:
                response = client.chat.completions.create(
                    model=os.environ.get("GROQ_MODEL", DEFAULT_MODEL),
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
            except APIError as error:
                raise ExtractionError(
                    "Groq API request failed. Check credentials, model access, network "
                    "and rate limits. No result was generated."
                ) from error
            content = None
            try:
                if not response.choices:
                    raise ValueError("Response has no choices")
                choice = response.choices[0]
                content = choice.message.content
                if choice.finish_reason != "stop":
                    raise ValueError("Response did not finish normally")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Response contains no JSON text")
                return _parse_response(content)
            except (ValueError, TypeError, ValidationError) as error:
                if attempt == 1:
                    raise ExtractionError(
                        "The model response was invalid on both attempts; no result was saved."
                    ) from error
                if isinstance(error, ValidationError):
                    details = json.dumps(error.errors(include_input=False, include_url=False), default=str)
                else:
                    details = str(error)
                if isinstance(content, str) and content:
                    messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "The response failed validation: " + details
                    + ". Extract again from the original document. Return only valid JSON; "
                    "never invent facts to repair the response.",
                })
    raise ExtractionError("No validated response was produced.")


def process_documents(data_path: str | Path, output_dir: str | Path) -> list[Path]:
    """Read demo/team records and save one metadata envelope per validated document.

    Validate all input records before API calls. Stop on failure; previously saved
    documents remain available. Existing output files are never overwritten.
    """
    records = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("Input must be a non-empty JSON list of documents")
    output_dir = Path(output_dir)
    destinations = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each document must be an object")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
            raise ValueError("case_id must contain only letters, digits, underscores or hyphens")
        if record.get("source") not in ("claimant", "police"):
            raise ValueError("source must be claimant or police")
        if not isinstance(record.get("text"), str) or not record["text"].strip():
            raise ValueError("Each document needs non-empty text")
        if type(record.get("synthetic")) is not bool:
            raise ValueError("Each document must declare synthetic as true or false")
        destination = output_dir / f"{case_id}_{record['source']}.json"
        if destination in destinations or destination.exists():
            raise ValueError(f"Duplicate or existing output: {destination.name}")
        destinations.append(destination)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for record, destination in zip(records, destinations):
        data = extract_incident(record["text"])
        envelope = {"case_id": record["case_id"], "source": record["source"],
                    "synthetic": record["synthetic"], "incident": data.model_dump()}
        with destination.open("x", encoding="utf-8") as file:
            json.dump(envelope, file, indent=2, ensure_ascii=False)
            file.write("\n")
        saved.append(destination)
    return saved


def main() -> None:
    project = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Extract incident documents using Groq")
    parser.add_argument("--data", type=Path, default=project / "data/demo_claims.json")
    parser.add_argument("--output", type=Path, default=project / "outputs")
    args = parser.parse_args()
    for path in process_documents(args.data, args.output):
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
