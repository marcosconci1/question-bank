"""Embeddings generation via OpenRouter API with bounded batching."""
import httpx

from . import config, errors


def embed(
    texts: list[str],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    batch_size: int | None = None,
) -> list[list[float]]:
    """Embed texts via OpenRouter batch embeddings API, preserving order.
    
    Raises:
        MissingApiKeyError: If API key is not configured.
        EmbeddingApiError: If request fails or API returns error status.
    """
    key = api_key if api_key is not None else config.OPENROUTER_API_KEY
    if not key:
        raise errors.MissingApiKeyError()

    if not texts:
        return []

    url = (base_url or config.EMBEDDING_BASE_URL).rstrip("/") + "/embeddings"
    model_name = model or config.EMBEDDING_MODEL
    batch_sz = batch_size or config.EMBED_BATCH_SIZE

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_sz):
        batch = texts[start : start + batch_sz]
        try:
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": model_name, "input": batch},
                )
        except httpx.HTTPError as exc:
            raise errors.EmbeddingApiError(f"Could not reach embedding API at {url}: {exc}") from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise errors.EmbeddingApiError(
                f"Embedding API returned HTTP {resp.status_code} from {url}: {resp.text[:200]}"
            )

        try:
            body = resp.json()
            data = body["data"]
            # OpenRouter / OpenAI embeddings return items with 'index'
            sorted_data = sorted(data, key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in sorted_data)
        except Exception as exc:
            raise errors.EmbeddingApiError(f"Failed to parse embedding API response: {exc}") from exc

    return vectors
