# AlphaBench Paper Runtime Overlay

The pinned paper commit contains a hard-coded third-party credential and a
user-home Qlib path. The overlay performs only three operational changes:

1. replace the LLM transport with the project Ark adapter;
2. read Qlib provider URI from QLIB_PROVIDER_URI;
3. bind FFO to HOST, defaulting to 127.0.0.1.
4. move the multiprocessing wrapper to module scope for macOS spawn support.
5. route generator validation through the configured Search FFO endpoint.

Search algorithms, prompts, Alpha158 seeds, filtering, metrics, and evaluator
logic are not changed.
