"""Image analysis tool — wraps Gemini Vision for site photo / submittal analysis."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool


def analyze_image(file_ref: str, prompt_hint: str = "") -> dict[str, Any]:
    """Analyze a site or document image with Gemini Vision.

    TODO: wire to Gemini Vision (uses the same google-genai client ADK already imports).
    Currently returns fixture/stub data so testing doesn't crash.

    Args:
        file_ref: Path or URI to the image file (local path, GCS URI, or HTTPS URL).
        prompt_hint: Optional hint about what to look for, e.g.
            "structural steel completion percentage" or "safety PPE compliance".

    Returns:
        Dict with keys:
            'visible_objects' (list[str]) — objects identified in the image.
            'estimated_completion_pct' (float | None) — if a scope is visible,
                the agent's estimate of percent complete (0–100).
            'safety_observations' (list[str]) — any safety concerns observed.
            'quality_observations' (list[str]) — any quality/defect observations.
            'narrative' (str) — plain-English description of the image contents.
    """
    # TODO: implement live Gemini Vision call using google.generativeai or
    #       google.genai.Client (the same client ADK uses). Pattern:
    #
    #   import google.generativeai as genai
    #   model = genai.GenerativeModel("gemini-2.5-pro")
    #   with open(file_ref, "rb") as f:
    #       img_bytes = f.read()
    #   response = model.generate_content([
    #       prompt_hint or "Describe this construction site image in detail.",
    #       {"mime_type": "image/jpeg", "data": img_bytes},
    #   ])
    #   return parse_vision_response(response.text)

    return {
        "visible_objects": [],
        "estimated_completion_pct": None,
        "safety_observations": [],
        "quality_observations": [],
        "narrative": (
            f"[STUB] analyze_image called with file_ref={file_ref!r}, "
            f"prompt_hint={prompt_hint!r}. "
            "TODO: implement live Gemini Vision call."
        ),
    }


analyze_image_tool = FunctionTool(func=analyze_image)
