from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import redact
from .trajectory import writer_from_env


class ModelError(RuntimeError):
    def __init__(self, message: str, *, attempts: int = 1):
        super().__init__(message)
        self.attempts = int(attempts)


@dataclass(frozen=True)
class ModelResponse:
    text: str
    response_id: str | None
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]
    attempts: int = 1


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct:
        return direct.strip()
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and isinstance(
                content.get("text"), str
            ):
                return content["text"].strip()
    choices = payload.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"].strip()
    raise ModelError("model response contains no text output")


def extract_usage(payload: dict[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    return int(input_tokens or 0), int(output_tokens or 0)


class ArkModelClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api_mode: str = "responses",
        timeout: int = 180,
    ):
        if not base_url.startswith("https://"):
            raise ValueError("Ark base_url must use HTTPS")
        if not api_key:
            raise ValueError("Ark API key is missing")
        if api_mode not in {"responses", "chat_completions"}:
            raise ValueError("unsupported Ark API mode")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_mode = api_mode
        self.timeout = int(timeout)

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        api_mode: str | None = None,
        timeout: int = 180,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> ArkModelClient:
        return cls(
            base_url=base_url or os.environ.get("ARK_BASE_URL", ""),
            api_key=api_key or os.environ.get("ARK_API_KEY", ""),
            model=model or os.environ.get("ARK_MODEL", ""),
            api_mode=api_mode or os.environ.get("ARK_API_MODE", "responses"),
            timeout=timeout,
        )

    def generate(
        self,
        *,
        prompt: str,
        system_prompt: str,
        temperature: float,
        json_output: bool = False,
        max_attempts: int = 3,
    ) -> ModelResponse:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.api_mode == "responses":
            endpoint = f"{self.base_url}/responses"
            payload: dict[str, Any] = {
                "model": self.model,
                "instructions": system_prompt,
                "input": prompt,
                "temperature": float(temperature),
            }
        else:
            endpoint = f"{self.base_url}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(temperature),
                "stream": False,
            }
            if json_output:
                payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        started = time.time()
        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                text = extract_response_text(raw)
                input_tokens, output_tokens = extract_usage(raw)
                result = ModelResponse(
                    text=text,
                    response_id=raw.get("id"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    raw=raw,
                    attempts=attempt,
                )
                self._record_call(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    response=result,
                    elapsed=time.time() - started,
                    attempt=attempt,
                )
                return result
            except urllib.error.HTTPError as exc:
                safe_body = redact(exc.read().decode("utf-8", errors="replace"))
                last_error = ModelError(f"Ark HTTP {exc.code}: {safe_body}")
                if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = ModelError(f"Ark request failed: {redact(str(exc))}")
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
        message = str(last_error) if last_error is not None else "Ark request failed"
        raise ModelError(message, attempts=attempt)

    def _record_call(
        self,
        *,
        prompt: str,
        system_prompt: str,
        response: ModelResponse,
        elapsed: float,
        attempt: int,
    ) -> None:
        record = {
            "call_id": f"call_{uuid.uuid4().hex}",
            "model": self.model,
            "api_mode": self.api_mode,
            "prompt": prompt,
            "system_prompt": system_prompt,
            "response_text": response.text,
            "response_id": response.response_id,
            "prompt_hash": _sha256(system_prompt + "\n" + prompt),
            "response_hash": _sha256(response.text),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "elapsed_seconds": elapsed,
            "attempt": attempt,
        }
        log_dir = os.getenv("HARNESS_MODEL_LOG_DIR")
        if log_dir:
            path = Path(log_dir)
            path.mkdir(parents=True, exist_ok=True)
            target = path / f"{record['call_id']}.json"
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        writer = writer_from_env()
        if writer:
            writer.append(
                "model_called",
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"prompt", "system_prompt", "response_text"}
                },
            )


def generate_text(
    prompt: str,
    *,
    model: str,
    system_prompt: str,
    temperature: float,
    json_output: bool,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int = 180,
    return_raw: bool = False,
) -> str | dict[str, Any]:
    client = ArkModelClient.from_env(
        model=model,
        api_mode=os.environ.get("ARK_API_MODE", "responses"),
        timeout=timeout,
        api_key=api_key,
        base_url=base_url,
    )
    result = client.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        json_output=json_output,
    )
    return result.raw if return_raw else result.text
