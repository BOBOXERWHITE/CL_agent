import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Load .env files into os.environ before the first get_settings() call.
# Precedence (Pydantic Settings v2 style):
#     1. Real environment variables (set by CI / docker / shell) -- always win
#     2. .env.local  (per-developer secrets, gitignored)
#     3. .env        (committed template defaults, optional)
#
# dotenv is a thin shim: it ONLY loads values for keys that are NOT already
# set, so CI exports are never overridden by a stray committed .env.
try:
    from dotenv import load_dotenv as _load_dotenv

    _BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
    # Order: .env first, .env.local second (load_dotenv does not overwrite
    # existing keys). To have .env.local take precedence, load it LAST with
    # override=False -- but that's the opposite of what we want. Instead,
    # load .env.local first (with override=False), then .env. The first
    # wins for any given key.
    _load_dotenv(_BACKEND_DIR / ".env.local", override=False)
    _load_dotenv(_BACKEND_DIR / ".env", override=False)
except ImportError:  # pragma: no cover - python-dotenv is a required dep
    pass


_log = logging.getLogger(__name__)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_csv_tuple(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default

    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or default


def _as_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    cors_allow_origins: tuple[str, ...]
    auth_enabled: bool
    auth_admin_tokens: tuple[str, ...]
    auth_operator_tokens: tuple[str, ...]
    auth_reviewer_tokens: tuple[str, ...]
    # JWT config (P1.1). When jwt_enabled is True, get_auth_context validates a
    # Bearer JWT instead of looking up a static token in the admin/operator/
    # reviewer lists. jwt_dev_token_endpoint_enabled gates the signing route
    # ``/api/auth/dev-token`` -- production must set this to False.
    jwt_enabled: bool
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    jwt_expire_minutes: int
    jwt_dev_token_endpoint_enabled: bool
    # Rate limiting (P1.6) -- disabled by default so unit tests don't trip.
    # Production turns it on; in-memory backend is good enough for a single
    # worker, swap to Redis (slowapi's storage_uri) for multi-worker.
    rate_limit_enabled: bool
    rate_limit_default: str  # e.g. "60/minute"
    rate_limit_chat_ask: str  # stricter because each call hits the LLM
    rate_limit_knowledge_upload: str  # stricter because each call writes MinIO
    rate_limit_auth_dev_token: str  # stops a curious dev from spam-signing
    database_url: str
    object_storage_provider: str
    object_storage_root: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket_name: str
    minio_secure: bool
    vector_store_provider: str
    milvus_host: str
    milvus_port: int
    milvus_collection_name: str
    # Milvus 2.5+ native BM25 (P6). When True, the Milvus collection
    # schema gains a ``content`` VARCHAR field and a ``sparse_vector``
    # SPARSE_FLOAT_VECTOR field bound by a ``BM25`` Function — Milvus
    # tokenizes + computes BM25 weights server-side, removing the need
    # for the SQL ``ILIKE`` lexical path. Off by default so existing
    # collections / deployments are not silently mutated; the migration
    # script ``backend/scripts/migrate_to_bm25.py`` does the schema
    # upgrade + reingestion explicitly.
    milvus_bm25_enabled: bool
    # Tokenizer for the BM25 analyzer. ``jieba`` for Chinese corpora,
    # ``standard`` for English / multi-lingual. Only consulted when
    # ``milvus_bm25_enabled`` is True.
    milvus_bm25_tokenizer: str
    # Lexical retrieval backend toggle. ``ilike`` keeps the legacy
    # PostgreSQL ``ILIKE`` + custom phrase-bonus scorer (current
    # default). ``milvus_bm25`` routes lexical_hits through Milvus'
    # native sparse BM25 search — requires ``milvus_bm25_enabled=True``
    # and a collection that has been migrated. Keeping these as two
    # separate flags lets us prepare the schema before flipping the
    # query path, and roll back the query path without touching the
    # schema.
    lexical_backend: str
    # P7 Phase A: mixed-domain policy supervisor execution mode.
    #   ``serial``   — legacy for-loop over planned profiles (default;
    #                  used by every existing test fixture)
    #   ``parallel`` — LangGraph ``Send`` fan-out: each profile runs
    #                  in its own worker invocation, the reducer node
    #                  waits for all workers to complete (barrier) and
    #                  aggregates. Same input/output contract as serial.
    #
    # Industry-mainstream "Orchestrator-Worker" pattern (LinkedIn SQL
    # agent / Klarna customer service / Uber Genie all use the same
    # LangGraph Send shape). Off by default so existing tests + the
    # docker-compose Milvus instance aren't hit with 3x concurrent
    # tool calls until operators explicitly opt in.
    agent_mixed_execution: str
    # P7 Phase B: LLM-driven ReAct planner inside policy_graph.
    # When False (default), ``_plan_node`` uses the legacy hardcoded
    # decision ("no observations → call policy_search; otherwise
    # finalize"), which is fast + deterministic + costs zero LLM tokens.
    # When True, the plan node asks the LLM at each step which tool to
    # call (or whether to finalize), enabling multi-tool / multi-cycle
    # ReAct as in the original Yao et al. 2022 paper. Any LLM error
    # falls back to the hardcoded plan with ``fallback_used=True`` so
    # one flaky call never crashes a question. Watch the eval gate's
    # judge_cost_usd_total when flipping this on — multi-cycle ReAct
    # can spend 3-5x more tokens per question.
    agent_react_llm_enabled: bool
    # Hard cap on ReAct cycles (plan + act + observe). Exists to bound
    # cost + latency when the LLM cannot decide to finalize. Matches
    # the constant pinned in ``policy_graph.MAX_REACT_STEPS`` so a
    # single env-var change can lower / raise both budgets together.
    agent_react_max_steps: int
    # P7 Phase C: agent-as-tool registration. When True, a ``call_agent``
    # Tool gets registered (lets one agent invoke another mid-execution)
    # and is added to the ReAct planner's allow-list. Off by default
    # because it widens blast radius — a buggy policy agent could trigger
    # a ticket re-route loop. Combined with ``agent_as_tool_max_depth``
    # (default 3) the recursion guard caps total LLM cost per question.
    agent_as_tool_enabled: bool
    # Maximum nested ``call_agent`` depth per request. The 4th call (after
    # 3 nested invocations) returns a failed CallAgentOutput instead of
    # recursing further, so an agent loop costs at most 3 * per-agent cost.
    agent_as_tool_max_depth: int
    embedding_provider: str
    embedding_model_name: str
    embedding_api_base_url: str
    embedding_api_key: str
    embedding_dimension: int
    embedding_batch_size: int
    embedding_max_retries: int
    embedding_request_dimensions: int | None
    embedding_encoding_format: str
    # Reranker (P2.4). Providers:
    #   heuristic       (default, no network) - in-process phrase+lexical bonus
    #   openai-compatible                     - /v1/rerank (Cohere/Jina/智谱 format)
    reranker_provider: str
    reranker_model_name: str
    reranker_api_base_url: str
    reranker_api_key: str
    reranker_top_n: int
    reranker_timeout_seconds: float
    # Caching (P2.7). Redis-backed when enabled; a no-op backend when
    # disabled so tests / dev without Redis don't break. Three TTLs
    # because cache invalidation semantics differ:
    #   - embedding cache:  ~30d; stable per (model, text)
    #   - retrieval cache:  ~1h;  stable per (tenant, query, filters)
    #   - answer cache:     ~10m; user-visible content, shortest ttl
    cache_enabled: bool
    cache_redis_url: str
    cache_embedding_ttl_seconds: int
    cache_retrieval_ttl_seconds: int
    cache_answer_ttl_seconds: int
    # Query rewriting (P2.6). Heuristic alias expansion is always on;
    # the LLM-driven branches are feature-flagged so CI + dev don't burn
    # LLM quota on every /api/chat/ask. HyDE = "hypothetical document
    # embeddings": ask the LLM to generate a plausible answer, then
    # retrieve against that answer's vector.
    query_rewrite_llm_enabled: bool
    query_rewrite_llm_variants: int
    hyde_enabled: bool
    # CRAG (Stage 3): after initial retrieval, ask the LLM whether evidence
    # is sufficient. If not, the engine re-retrieves with the evaluator's
    # suggested queries and merges results. ``crag_max_rounds`` caps the
    # extra retrieval rounds; anti-loop guards in the engine break early
    # when missing aspects don't change or no new chunks are added.
    crag_enabled: bool
    crag_max_rounds: int
    crag_sufficiency_threshold: float
    crag_evaluator_timeout_seconds: float
    # Agent router (P3.2). Three strategies; each falls back to the next:
    #   llm       — LLM classifies intent (most flexible, costs tokens)
    #   embedding — compute similarity against intent exemplars (no LLM calls)
    #   keyword   — substring match against hand-curated lists (legacy default)
    # Chain: primary → embedding → keyword. Keyword always works.
    agent_router_provider: str
    chunk_size: int
    chunk_overlap: int
    chat_top_k: int
    chat_confidence_threshold: float
    # P11: how many prior (user, assistant) turns to load from ChatMessage
    # and prepend to the LLM messages array. Caps the prompt growth; set
    # to 0 to disable multi-turn context entirely.
    chat_history_max_turns: int
    rag_dense_candidate_multiplier: int
    rag_lexical_candidate_multiplier: int
    rag_rrf_k: int
    rag_max_chunks_per_document: int
    llm_provider: str
    llm_model_name: str
    llm_api_base_url: str
    llm_api_key: str
    celery_broker_url: str
    celery_result_backend: str
    celery_task_always_eager: bool
    # P5.1: OTEL settings. Empty ``otel_exporter_otlp_endpoint`` = no-op
    # tracer (deterministic in-memory span recording, no network).
    # Setting this to ``http://collector:4318`` enables real OTLP export.
    otel_service_name: str
    otel_exporter_otlp_endpoint: str
    otel_exporter_otlp_headers: str
    # P8 follow-up: pluggable tracing backend selector. ``auto`` (default)
    # derives the active backend from whichever convenience profile env
    # is filled in:
    #   - PHOENIX_ENDPOINT set  → export to Phoenix
    #   - LANGSMITH_API_KEY set → export to LangSmith (auto-builds the
    #     endpoint + x-api-key header, no need to remember the URL)
    #   - both set              → dual-export (Phoenix for local /
    #     LangSmith for team UI in same run)
    #   - neither set + raw OTEL_EXPORTER_OTLP_ENDPOINT set → that wins
    #     (vendor-neutral escape hatch for Jaeger / Tempo / Datadog)
    # Explicit values (``phoenix`` / ``langsmith`` / ``both`` / ``none``)
    # force the choice regardless of which env vars are populated — useful
    # in CI where you want to suppress all export without touching other
    # env vars.
    tracing_backend: str
    phoenix_endpoint: str
    langsmith_api_key: str
    langsmith_project: str
    langsmith_endpoint: str
    # P5.5: task_run cleanup retention. 0 or negative disables the cron
    # so dev environments never have rows deleted automatically.
    task_run_retention_days: int
    # Eval LLM-as-judge (P0). When ``eval_judge_enabled`` is True, the
    # eval runner asks an LLM to grade ``answer_correctness`` and
    # ``faithfulness`` instead of relying on keyword AND-matching alone.
    # Disabled by default so dev / CI without a real gateway keeps the
    # current keyword behaviour. ``eval_judge_model_name`` falls back to
    # ``llm_model_name`` when empty so most callers never need to set it.
    eval_judge_enabled: bool
    eval_judge_model_name: str
    eval_judge_timeout_seconds: float
    # P2: judge token pricing in USD per 1K tokens. Zero by default
    # (cost reporting opt-in) so anyone running on a free / metered-
    # by-different-unit gateway doesn't see misleading $0.00 numbers.
    # Look up your gateway's published rates and plug in here, e.g.
    # DeepSeek v3.2: prompt $0.00027/1K, completion $0.00109/1K.
    eval_judge_price_prompt_per_1k_usd: float
    eval_judge_price_completion_per_1k_usd: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Travel Ops Copilot API"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        cors_allow_origins=_as_csv_tuple(
            os.getenv("CORS_ALLOW_ORIGINS"),
            default=(
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
                "http://127.0.0.1:4173",
            ),
        ),
        auth_enabled=_as_bool(os.getenv("AUTH_ENABLED"), default=False),
        auth_admin_tokens=_as_csv_tuple(os.getenv("AUTH_ADMIN_TOKENS"), default=("admin-token",)),
        auth_operator_tokens=_as_csv_tuple(
            os.getenv("AUTH_OPERATOR_TOKENS"), default=("operator-token",)
        ),
        auth_reviewer_tokens=_as_csv_tuple(
            os.getenv("AUTH_REVIEWER_TOKENS"), default=("reviewer-token",)
        ),
        jwt_enabled=_as_bool(os.getenv("JWT_ENABLED"), default=False),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "dev-only-insecure-change-me").strip(),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256").strip(),
        jwt_issuer=os.getenv("JWT_ISSUER", "travel-ops-copilot").strip(),
        jwt_audience=os.getenv("JWT_AUDIENCE", "travel-ops-copilot-api").strip(),
        jwt_expire_minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "60")),
        jwt_dev_token_endpoint_enabled=_as_bool(
            os.getenv("JWT_DEV_TOKEN_ENDPOINT_ENABLED"), default=True
        ),
        rate_limit_enabled=_as_bool(os.getenv("RATE_LIMIT_ENABLED"), default=False),
        rate_limit_default=os.getenv("RATE_LIMIT_DEFAULT", "60/minute"),
        rate_limit_chat_ask=os.getenv("RATE_LIMIT_CHAT_ASK", "20/minute"),
        rate_limit_knowledge_upload=os.getenv("RATE_LIMIT_KNOWLEDGE_UPLOAD", "10/minute"),
        rate_limit_auth_dev_token=os.getenv("RATE_LIMIT_AUTH_DEV_TOKEN", "10/minute"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://travel_ops:travel_ops@localhost:5432/travel_ops",
        ),
        object_storage_provider=os.getenv("OBJECT_STORAGE_PROVIDER", "minio").lower(),
        object_storage_root=os.getenv("OBJECT_STORAGE_ROOT", "./data/object-store"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        minio_secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        minio_bucket_name=os.getenv("MINIO_BUCKET_NAME", "knowledge"),
        minio_secure=_as_bool(os.getenv("MINIO_SECURE"), default=False),
        vector_store_provider=os.getenv("VECTOR_STORE_PROVIDER", "milvus").lower(),
        milvus_host=os.getenv("MILVUS_HOST", "localhost"),
        milvus_port=int(os.getenv("MILVUS_PORT", "19530")),
        milvus_collection_name=os.getenv("MILVUS_COLLECTION_NAME", "knowledge_chunks"),
        milvus_bm25_enabled=_as_bool(os.getenv("MILVUS_BM25_ENABLED"), default=False),
        milvus_bm25_tokenizer=os.getenv("MILVUS_BM25_TOKENIZER", "jieba").strip().lower(),
        lexical_backend=os.getenv("LEXICAL_BACKEND", "ilike").strip().lower(),
        agent_mixed_execution=os.getenv("AGENT_MIXED_EXECUTION", "serial").strip().lower(),
        agent_react_llm_enabled=_as_bool(os.getenv("AGENT_REACT_LLM_ENABLED"), default=False),
        agent_react_max_steps=int(os.getenv("AGENT_REACT_MAX_STEPS", "8")),
        agent_as_tool_enabled=_as_bool(os.getenv("AGENT_AS_TOOL_ENABLED"), default=False),
        agent_as_tool_max_depth=int(os.getenv("AGENT_AS_TOOL_MAX_DEPTH", "3")),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "deterministic").lower(),
        embedding_model_name=os.getenv("EMBEDDING_MODEL_NAME", "deterministic-hash-embedding"),
        embedding_api_base_url=os.getenv(
            "EMBEDDING_API_BASE_URL", os.getenv("LLM_API_BASE_URL", "")
        ).strip(),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_API_KEY", "")).strip(),
        embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "16")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
        embedding_max_retries=int(os.getenv("EMBEDDING_MAX_RETRIES", "2")),
        embedding_request_dimensions=_as_optional_int(os.getenv("EMBEDDING_REQUEST_DIMENSIONS")),
        embedding_encoding_format=os.getenv("EMBEDDING_ENCODING_FORMAT", "float").strip(),
        reranker_provider=os.getenv("RERANKER_PROVIDER", "heuristic").strip().lower(),
        reranker_model_name=os.getenv("RERANKER_MODEL_NAME", "").strip(),
        reranker_api_base_url=os.getenv("RERANKER_API_BASE_URL", "").strip(),
        reranker_api_key=os.getenv("RERANKER_API_KEY", "").strip(),
        reranker_top_n=int(os.getenv("RERANKER_TOP_N", "10")),
        reranker_timeout_seconds=float(os.getenv("RERANKER_TIMEOUT_SECONDS", "5.0")),
        cache_enabled=_as_bool(os.getenv("CACHE_ENABLED"), default=False),
        cache_redis_url=os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/2").strip(),
        cache_embedding_ttl_seconds=int(os.getenv("CACHE_EMBEDDING_TTL_SECONDS", "2592000")),
        cache_retrieval_ttl_seconds=int(os.getenv("CACHE_RETRIEVAL_TTL_SECONDS", "3600")),
        cache_answer_ttl_seconds=int(os.getenv("CACHE_ANSWER_TTL_SECONDS", "600")),
        agent_router_provider=os.getenv("AGENT_ROUTER_PROVIDER", "keyword").strip().lower(),
        query_rewrite_llm_enabled=_as_bool(os.getenv("QUERY_REWRITE_LLM_ENABLED"), default=False),
        query_rewrite_llm_variants=int(os.getenv("QUERY_REWRITE_LLM_VARIANTS", "2")),
        hyde_enabled=_as_bool(os.getenv("HYDE_ENABLED"), default=False),
        crag_enabled=_as_bool(os.getenv("CRAG_ENABLED"), default=False),
        crag_max_rounds=int(os.getenv("CRAG_MAX_ROUNDS", "2")),
        crag_sufficiency_threshold=float(os.getenv("CRAG_SUFFICIENCY_THRESHOLD", "0.7")),
        crag_evaluator_timeout_seconds=float(os.getenv("CRAG_EVALUATOR_TIMEOUT_SECONDS", "8.0")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "450")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "1")),
        chat_top_k=int(os.getenv("CHAT_TOP_K", "3")),
        chat_confidence_threshold=float(os.getenv("CHAT_CONFIDENCE_THRESHOLD", "0.2")),
        chat_history_max_turns=max(0, int(os.getenv("CHAT_HISTORY_MAX_TURNS", "5"))),
        rag_dense_candidate_multiplier=int(os.getenv("RAG_DENSE_CANDIDATE_MULTIPLIER", "3")),
        rag_lexical_candidate_multiplier=int(os.getenv("RAG_LEXICAL_CANDIDATE_MULTIPLIER", "12")),
        rag_rrf_k=int(os.getenv("RAG_RRF_K", "60")),
        rag_max_chunks_per_document=int(os.getenv("RAG_MAX_CHUNKS_PER_DOCUMENT", "2")),
        llm_provider=os.getenv("LLM_PROVIDER", "deterministic").lower(),
        llm_model_name=os.getenv("LLM_MODEL_NAME", "deterministic-policy-client"),
        llm_api_base_url=os.getenv("LLM_API_BASE_URL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        celery_task_always_eager=_as_bool(os.getenv("CELERY_TASK_ALWAYS_EAGER"), default=True),
        otel_service_name=os.getenv("OTEL_SERVICE_NAME", "travel-ops-copilot"),
        otel_exporter_otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip(),
        otel_exporter_otlp_headers=os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip(),
        tracing_backend=os.getenv("TRACING_BACKEND", "auto").strip().lower(),
        phoenix_endpoint=os.getenv("PHOENIX_ENDPOINT", "").strip(),
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY", "").strip(),
        langsmith_project=os.getenv("LANGSMITH_PROJECT", "cl-agent").strip(),
        langsmith_endpoint=os.getenv(
            "LANGSMITH_ENDPOINT",
            "https://api.smith.langchain.com/otel/v1/traces",
        ).strip(),
        task_run_retention_days=int(os.getenv("TASK_RUN_RETENTION_DAYS") or "90"),
        eval_judge_enabled=_as_bool(os.getenv("EVAL_JUDGE_ENABLED"), default=False),
        eval_judge_model_name=os.getenv("EVAL_JUDGE_MODEL_NAME", "").strip(),
        eval_judge_timeout_seconds=float(os.getenv("EVAL_JUDGE_TIMEOUT_SECONDS", "20.0")),
        eval_judge_price_prompt_per_1k_usd=float(
            os.getenv("EVAL_JUDGE_PRICE_PROMPT_PER_1K_USD", "0.0")
        ),
        eval_judge_price_completion_per_1k_usd=float(
            os.getenv("EVAL_JUDGE_PRICE_COMPLETION_PER_1K_USD", "0.0")
        ),
    )
