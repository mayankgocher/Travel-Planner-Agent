"""LangChain/Groq bridge. No client or request is created during imports."""
from dataclasses import dataclass

from groq import APIError
from langchain_core.exceptions import OutputParserException
from langchain_groq import ChatGroq
from langsmith import tracing_context
from pydantic import BaseModel, ValidationError

from backend.config import Settings


class ModelCallError(RuntimeError):
    """Safe public error; never carries provider response bodies or credentials."""
    http_status: int | None = None


@dataclass(frozen=True)
class StructuredResult:
    parsed: BaseModel
    usage: dict[str, int]


def create_model(settings: Settings, *, http_client=None) -> ChatGroq:
    # Only this selected model's structured-output path is being validated.
    if settings.groq_model != "openai/gpt-oss-120b":
        raise ValueError("This integration currently targets openai/gpt-oss-120b")
    return ChatGroq(model=settings.groq_model, api_key=settings.require_provider_key("groq"),
                    temperature=0, max_tokens=2048, timeout=45, max_retries=0,
                    reasoning_effort="low", model_kwargs={"include_reasoning": False},
                    http_client=http_client)


def invoke_structured(model: ChatGroq, schema: type[BaseModel], messages: list) -> StructuredResult:
    """One attempt, strict native JSON schema; no tools or parser repair loops.

    We retain parsed business data and usage, never the raw/private reasoning.
    Semantic truthfulness still needs evaluation even when the schema is valid.
    """
    try:
        # Keep optional hosted tracing off for this initial integration.
        with tracing_context(enabled=False):
            result = model.with_structured_output(schema, method="json_schema", strict=True,
                                                  include_raw=True).invoke(messages)
        raw, parsed = result["raw"], result["parsed"]
        if result.get("parsing_error") is not None or parsed is None:
            raise ValueError("Invalid structured answer")
        if raw.response_metadata.get("finish_reason") != "stop":
            raise ValueError("Incomplete model answer")
        usage = {k: v for k, v in (raw.usage_metadata or {}).items()
                 if k in ("input_tokens", "output_tokens", "total_tokens")
                 and type(v) is int and v >= 0}
        return StructuredResult(parsed=schema.model_validate(parsed), usage=usage)
    except (APIError, OutputParserException, ValidationError, ValueError, KeyError, TypeError) as exc:
        error = ModelCallError(f"Model call failed ({type(exc).__name__}); no preferences were applied.")
        error.http_status = getattr(exc, "status_code", None)
        raise error from None
