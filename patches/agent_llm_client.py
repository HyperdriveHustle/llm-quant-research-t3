"""Security/model-provider overlay for the pinned AlphaBench paper runtime.

Search algorithms and prompts remain upstream-owned. This file only removes
hard-coded credentials and delegates transport to the project Ark adapter.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from quant_harness.model import generate_text


def call_llm(
    prompt,
    model="deepseek-chat",
    api_key=None,
    base_url=None,
    json_output=False,
    system_prompt="You are a helpful assistant.",
    temperature=1.0,
    local=False,
    local_port=8000,
    return_raw=False,
    max_try=5,
    timeout=120,
    service_provider="all",
    save_raw_dir=None,
):
    if local:
        raise ValueError("local model mode is disabled by the paper harness overlay")
    return generate_text(
        prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        json_output=json_output,
        system_prompt=system_prompt,
        temperature=temperature,
        timeout=timeout,
        return_raw=return_raw,
    )


def batch_call_llm(
    prompts,
    model="deepseek-chat",
    api_key=None,
    base_url=None,
    json_output=False,
    system_prompt="You are a helpful assistant.",
    temperature=1.0,
    local=False,
    local_port=8000,
    latency=None,
    num_workers=4,
    return_raw=False,
    verbose=False,
    timeout=None,
    service_provider="all",
):
    results = [None] * len(prompts)

    def worker(index, prompt):
        if latency:
            time.sleep(latency)
        return index, call_llm(
            prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            json_output=json_output,
            system_prompt=system_prompt,
            temperature=temperature,
            local=local,
            local_port=local_port,
            return_raw=return_raw,
            timeout=timeout or 120,
            service_provider=service_provider,
        )

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(worker, index, prompt)
            for index, prompt in enumerate(prompts)
        ]
        for future in as_completed(futures):
            index, value = future.result()
            results[index] = value
    return results
