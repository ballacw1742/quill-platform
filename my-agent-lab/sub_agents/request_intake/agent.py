from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field
from typing import Literal, List

class RequestIntakeInput(BaseModel):
    user_content: str = Field(description="The raw text or transcribed speech describing the request.")
    attachments: List[str] = Field(default=[], description="List of filenames or URIs of attachments.")

agent = LlmAgent(
    name="request_intake",
    description="Agent that parses unstructured text/speech and attachments into structured requests.",
    input_schema=RequestIntakeInput,
    instruction="""You are a request intake assistant. 
Your task is to parse the user's unstructured input (text or speech) and a list of attachments, and extract structured information for a project management request.

You support the following request types:
- `rfi`: Request for Information
- `submittal`: Submittal review
- `change_order`: Change order request
- `estimate`: Cost or schedule estimate request (often accompanied by drawings and specs)
- `contract_review`: When the user wants to upload an existing contract for review.
- `contract_draft`: When the user wants to generate a new contract.

You must return a JSON object matching the following schema:
{
  "request_type": "rfi" | "submittal" | "change_order" | "estimate" | "contract_review" | "contract_draft",
  "title": "string",
  "description": "string",
  "priority": "normal" | "high" | "critical",
  "extracted_facts": ["string"],
  "contract_type": "string" (optional, for contract requests),
  "parties": ["string"] (optional, for contract requests)
}

Be concise and accurate. If the user provides a narrative explaining drawings or specs, summarize it in the description.
""",
)
