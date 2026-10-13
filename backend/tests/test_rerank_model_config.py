"""A Bedrock rerank model in a shipped profile must be a full foundation-model ARN.

LiteLLM (v1.91) passes the model string after `bedrock/` to Bedrock's Rerank API as
`modelArn` unchanged, so `bedrock/cohere.rerank-v3-5:0` is refused as an invalid ARN
and every rerank silently falls back to vector order (seen live, 2026-10-13). The
ARN's region must also be the one the entry names, or the call leaves the region the
operator pinned.
"""
import re
from pathlib import Path

import yaml

HELM = Path(__file__).resolve().parents[2] / "helm/datapond"
ARN = re.compile(r"^bedrock/arn:aws:bedrock:(?P<region>[a-z0-9-]+)::foundation-model/.+")


def _bedrock_rerank_entries():
    for f in sorted(HELM.glob("values*.yaml")):
        values = yaml.safe_load(f.read_text()) or {}
        for m in (((values.get("litellm") or {}).get("config") or {}).get("model_list") or []):
            params = m.get("litellm_params") or {}
            if "rerank" in m.get("model_name", "") and str(params.get("model", "")).startswith("bedrock/"):
                yield f.name, params


def test_at_least_one_profile_ships_a_bedrock_reranker():
    assert list(_bedrock_rerank_entries())


def test_every_bedrock_reranker_is_a_foundation_model_arn_in_its_own_region():
    for name, params in _bedrock_rerank_entries():
        match = ARN.match(params["model"])
        assert match, f"{name}: {params['model']} is not a foundation-model ARN"
        assert match["region"] == params.get("aws_region_name"), name
