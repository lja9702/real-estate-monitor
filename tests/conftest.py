"""테스트 공용 fixture."""

from __future__ import annotations

import json
import pathlib

import pytest

from myhouse.constants import TradeType
from myhouse.db.engine import init_db, make_engine
from myhouse.naver.parser import ArticleDTO, compute_cluster_key

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def newland_payload() -> dict:
    return json.loads((FIXTURES / "newland_articles.json").read_text(encoding="utf-8"))


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "test.db")
    init_db(eng)
    return eng


def make_dto(
    article_no: str,
    *,
    complex_no: str = "111",
    trade_type: TradeType = TradeType.SALE,
    price_deal: int | None = 158000,
    price_rent: int | None = None,
    area_excl: float | None = 81.0,
    area_name: str | None = "82A",
    floor_num: int | None = 12,
    direction: str | None = "남향",
) -> ArticleDTO:
    """테스트용 ArticleDTO 헬퍼 (cluster_key 자동 계산)."""
    ck = compute_cluster_key(complex_no, area_name, floor_num, None, direction, trade_type)
    return ArticleDTO(
        article_no=article_no,
        complex_no=complex_no,
        trade_type=trade_type,
        price_deal=price_deal,
        price_rent=price_rent,
        area_excl=area_excl,
        area_supply=None,
        area_name=area_name,
        floor_info=f"{floor_num}/15" if floor_num is not None else None,
        floor_num=floor_num,
        direction=direction,
        dong="501동",
        feature_desc="테스트",
        realtor_name="테스트중개",
        confirm_date="2026-06-19",
        article_url=f"https://m.land.naver.com/article/info/{article_no}",
        cluster_key=ck,
    )
