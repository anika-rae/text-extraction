# Incident extraction

A small Python module that extracts road traffic incident facts from claimant narratives
and police reports using LLaMA through the official Groq SDK. Both sources use the same
Pydantic v2 schema. Documents are processed independently; vehicle IDs are local to each
document. No comparison, vehicle matching or fraud detection is performed.

## Files

- `schemas.py`: strict `Vehicle`, `Impact` and `IncidentData` models.
- `prompts.py`: English instructions and three synthetic few-shot examples.
- `extraction.py`: API calls, one validation retry, batch processing and JSON saving.
- `data/demo_claims.json`: three clearly marked synthetic demonstration documents.
- `Incident_extraction.ipynb`: Google Drive / Colab setup and execution.
- `tests/test_extraction.py`: offline tests using Python's standard unittest library.
- `outputs/`: validated extraction results; empty until extraction is run.

## Google Drive and Colab

1. Upload the `incident_extraction` folder to Google Drive, preserving its files and subfolders.
   If using the ZIP archive, unzip it first; Colab needs the extracted folder.
2. Open `Incident_extraction.ipynb` using Google Colab.
3. In Colab Secrets, add `GROQ_API_KEY` and enable notebook access. Never put a key in source
   code, notebook cells, output files or a shared Drive folder.
4. Run the mount cell and set `project_relative_path` to the folder's location relative to
   My Drive (for example, `university/incident_extraction`). No user-specific path is needed.
5. Run the dependency installation, credential and extraction cells in order.
6. Inspect JSON results in `outputs`. Existing files are protected: select a different
   output subfolder for another run, or remove only results you intentionally wish to replace.

The notebook imports the Python package rather than duplicating extraction logic.
Google Drive paths and Colab Secrets are handled only by the notebook.

## Local Python (3.10 or newer)

Run from the directory containing the `incident_extraction` folder:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r incident_extraction/requirements.txt
```

Set `GROQ_API_KEY` securely in your process environment (for example through your IDE's
secret settings). Then run:

```bash
python -m incident_extraction.extraction --data incident_extraction/data/demo_claims.json --output incident_extraction/outputs
python -m unittest discover -s incident_extraction/tests -v
```

For integration:

```python
from incident_extraction.extraction import extract_incident

claimant_data = extract_incident(claimant_text)
police_data = extract_incident(police_text)
print(claimant_data.model_dump_json(indent=2))
```

The default model is `llama-3.3-70b-versatile` with temperature 0 and Groq's
`response_format={"type": "json_object"}`. JSON object mode is not schema enforcement:
every response is additionally checked locally. Set `GROQ_MODEL` only to a currently
available Groq LLaMA model supporting JSON object mode if the default is unavailable.
Model access and availability must be checked with your account. Documentation:
https://console.groq.com/docs/models and https://console.groq.com/docs/structured-outputs.
Requests use a 60-second timeout and disable SDK retries. API errors (including rate limits,
authentication and model access errors) produce `ExtractionError` without automatic retry.
Invalid, empty, truncated, malformed or schema-invalid model responses trigger exactly
one corrective request with validation feedback. A second invalid response raises
`ExtractionError`; it never becomes a fabricated successful result.

## Team input and output format

Replace the demo file or pass another JSON file. Each record has:

```json
[
  {
    "case_id": "case_001",
    "source": "claimant",
    "synthetic": false,
    "text": "The team's original narrative goes here."
  },
  {
    "case_id": "case_001",
    "source": "police",
    "synthetic": false,
    "text": "The team's original police report goes here."
  }
]
```

`case_id` permits letters, digits, underscores and hyphens. Each case/source pair must
be unique. For multiple reports of the same type, use distinct case IDs. The synthetic
flag is required and preserved so demonstrations cannot be mistaken for team data.
All input records and output collisions are checked before API calls. Batch processing
stops on a failed extraction, retaining any earlier successful files.
Each file is named `<case_id>_<source>.json` and contains:

```json
{
  "case_id": "case_001",
  "source": "claimant",
  "synthetic": false,
  "incident": {
    "date": null,
    "time": null,
    "time_approximate": null,
    "location": null,
    "vehicle_count": null,
    "vehicles": [],
    "claimant_vehicle_id": null,
    "fault_vehicle_id": null,
    "incident_type": null,
    "impacts": []
  }
}
```

Metadata belongs to the saved envelope, not to `IncidentData`. Incomplete or ambiguous
dates become null; known dates must be real calendar dates in YYYY-MM-DD format.
Times use HH:MM. Partial impacts can use null IDs or regions. A known total vehicle
count may exceed the number of individually identifiable vehicles; missing vehicles
are never invented to satisfy the count. `time_approximate` can remain null when precision
is unknown, and must be null when no time is available.

## Validation and limitations

Offline tests check schema constraints, few-shot examples, successful request counts,
exactly one retry, API errors, empty responses, JSON parsing and saving both source types.
They do not call Groq or measure factual extraction accuracy. Pydantic checks structure
and consistency; it cannot prove that a generated fact is supported by the source.
Review actual model outputs against the original documents, especially fault and impact
references. Prompts reduce hallucinations but cannot guarantee their absence.

Live validation procedure: configure the key, run the three synthetic documents through
the CLI or notebook, verify three output files, and review each against its source text.
The first narrative should yield a rear-end impact and no established fault; the second
should identify the Ford as explicitly at fault; the third should not invent vehicle
identities. Then repeat with authorized team documents. Text is sent to Groq and results
may contain personal information; use appropriate data and protect Drive access.

During project creation, live Groq extraction was not run because no API key was available.
Colab execution requires your Google account and must be verified in Colab.
