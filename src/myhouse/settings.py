"""설정 로드.

- 비밀값(텔레그램 토큰 등)은 `.env` / 환경변수 → `Settings` (pydantic-settings)
- 타겟·필터는 `config.yaml` → `Config` (pydantic 모델, 타입 검증)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import TradeType


class Settings(BaseSettings):
    """비밀값 — `.env` 또는 환경변수에서 로드."""

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None  # 쉼표 구분 복수 가능: "111,222,333"
    telegram_allowlist: str | None = None  # 봇 명령을 받을 chat_id 화이트리스트(쉼표 구분)
    telegram_join_code: str | None = None  # 초대코드 — /join <코드> 로 셀프 등록(미설정이면 셀프조인 off)
    naver_map_client_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)

    @staticmethod
    def _split_ids(raw: str | None) -> list[str]:
        if not raw:
            return []
        return [cid.strip() for cid in raw.split(",") if cid.strip()]

    @property
    def telegram_chat_ids(self) -> list[str]:
        """TELEGRAM_CHAT_ID를 쉼표로 분리한 리스트. 미설정이면 빈 리스트."""
        return self._split_ids(self.telegram_chat_id)

    @property
    def telegram_allowlist_ids(self) -> list[str]:
        """봇 명령 허용 chat_id 목록. TELEGRAM_ALLOWLIST 우선, 없으면 TELEGRAM_CHAT_ID 폴백.

        빈 리스트면 '전체 허용'(역호환). 지인 소수 개방 시 여기에 chat_id 를 명시한다.
        """
        return self._split_ids(self.telegram_allowlist) or self.telegram_chat_ids


class FilterSpec(BaseModel):
    """단지별 매물 필터. defaults + target.overrides 병합 결과."""

    trade_types: list[TradeType] = Field(default_factory=lambda: [TradeType.SALE])
    real_estate_type: str = "APT:ABYG:JGC"  # 아파트:분양권:재건축 (재건축 단지도 포함)
    area_excl_min_m2: float | None = None
    area_excl_max_m2: float | None = None
    area_supply_min_m2: float | None = None  # 공급면적(area1) 하한
    area_supply_max_m2: float | None = None  # 공급면적(area1) 상한
    price_min_manwon: int | None = None
    price_max_manwon: int | None = None
    floor_min: int | None = None

    @field_validator("trade_types", mode="before")
    @classmethod
    def _non_empty(cls, v: Any) -> Any:
        if v is None or v == []:
            return [TradeType.SALE]
        return v


class DiscoverSpec(BaseModel):
    """region 타겟의 단지 자동탐색 필터 (Phase 3)."""

    name_includes: list[str] = Field(default_factory=list)
    name_excludes: list[str] = Field(default_factory=list)
    min_total_households: int | None = None


class TargetSpec(BaseModel):
    """수집 타겟 한 건 (단지 직접 지정 또는 지역 자동탐색)."""

    kind: Literal["complex", "region"]
    label: str = ""
    # kind == "complex"
    complex_no: str | None = None
    lat: float | None = None
    lon: float | None = None
    cortar_no: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    # kind == "region"
    discover: DiscoverSpec = Field(default_factory=DiscoverSpec)

    @field_validator("complex_no", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        return None if v is None else str(v)


class AppConfig(BaseModel):
    timezone: str = "Asia/Seoul"
    db_path: str = "data/myhouse.db"
    dashboard_url: str = "http://localhost:8765"
    env_file: str = ".env"  # 인스턴스별 텔레그램 토큰/채널 파일
    removal_debounce_hours: float = 20.0
    request_delay_seconds: tuple[float, float] = (1.0, 3.0)
    notify_on_no_change: bool = False
    headless: bool = True  # Playwright 브라우저 표시 여부(디버그 시 false)


class DealsConfig(BaseModel):
    """실거래(국토부, 네이버 prices/real 경유) 수집 설정."""

    enabled: bool = True
    trade_types: list[TradeType] = Field(default_factory=lambda: [TradeType.SALE])
    years: int = 3  # 실거래 조회 기간(년). 최신 거래가 앞에 온다.
    scope: Literal["all", "starred"] = "all"  # 전체 추적 단지 | 관심 단지(별표)만
    use_area_filter: bool = True  # 면적 필터(공급/전용)로 평형을 제한해 호출량↓
    notify_on_no_change: bool = False  # 신규 실거래 0건이어도 알림 보낼지

    @field_validator("trade_types", mode="before")
    @classmethod
    def _non_empty(cls, v: Any) -> Any:
        if v is None or v == []:
            return [TradeType.SALE]
        return v


class PermitsConfig(BaseModel):
    """토지거래허가(서울시 land.seoul.go.kr) 수집 설정.

    실거래의 *선행* 신호(거래 완료 전 허가). 응답에 가격·면적이 없어 '단지에서 허가 N건'
    수준으로만 쓴다. 추적단지가 있는 서울 자치구만 조회하고, 지번이 매칭된 단지만 알린다.
    """

    enabled: bool = True
    days: int = 60  # 조회 기간(일). 서버 제약상 최대 62 로 자동 캡.
    scope: Literal["all", "starred"] = "all"  # 전체 추적 단지 | 관심(별표)만
    use_purpose_filter: bool = True  # 이용목적='주거용'만 매칭(아파트 거래로 한정)
    notify_on_no_change: bool = False  # 신규 허가 0건이어도 알림 보낼지

    @field_validator("days")
    @classmethod
    def _cap_days(cls, v: int) -> int:
        return min(max(v, 1), 62)


class RegionSpec(BaseModel):
    """주간 탐색 대상 지역 1개 — 지도 bbox(+맥락용 cortarNo)."""

    name: str  # 표시 라벨 ("강남구")
    cortar_no: str = ""  # 맥락/referer용 (서버측 필터 아님)
    # bbox = [leftLon, rightLon, topLat, bottomLat]
    bbox: list[float] = Field(default_factory=list)

    @field_validator("cortar_no", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        return "" if v is None else str(v)

    @field_validator("bbox")
    @classmethod
    def _bbox_len(cls, v: list[float]) -> list[float]:
        if len(v) != 4:
            raise ValueError("bbox 는 [leftLon, rightLon, topLat, bottomLat] 4개여야 합니다")
        return v

    @property
    def bbox_tuple(self) -> tuple[float, float, float, float]:
        left, right, top, bottom = self.bbox
        return (left, right, top, bottom)


class DiscoverConfig(BaseModel):
    """주간 신규편입 단지 탐색(single-markers 기반) 설정.

    지정 지역들을 주 1회 훑어 가격대(매매)·세대수·면적 조건에 맞는 단지를 모으고,
    기존 추적/기탐색 단지에 없던 '신규 편입' 단지만 텔레그램으로 알린다(추가는 사용자가 /add).
    """

    enabled: bool = False
    trade_type: TradeType = TradeType.SALE
    real_estate_type: str = "APT:ABYG:JGC"
    price_min_manwon: int = 150000  # 15억
    price_max_manwon: int = 260000  # 26억
    area_supply_min_m2: float | None = 66.0  # 마커 minArea/maxArea(공급 추정) 서버측 필터
    area_supply_max_m2: float | None = 131.0
    min_households: int | None = 300
    zoom: int = 13
    seed_complex_no: str = ""  # 토큰 시드(빈값이면 첫 region/타겟/947 폴백)
    notify_on_no_change: bool = False  # 신규 0건이어도 알림 보낼지
    regions: list[RegionSpec] = Field(default_factory=list)

    @field_validator("seed_complex_no", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        return "" if v is None else str(v)


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    defaults: FilterSpec = Field(default_factory=FilterSpec)
    deals: DealsConfig = Field(default_factory=DealsConfig)
    permits: PermitsConfig = Field(default_factory=PermitsConfig)
    discover: DiscoverConfig = Field(default_factory=DiscoverConfig)
    targets: list[TargetSpec] = Field(default_factory=list)

    def effective_filter(self, target: TargetSpec) -> FilterSpec:
        """defaults 위에 target.overrides 를 덮어쓴 유효 필터를 재검증해 반환."""
        merged = {**self.defaults.model_dump(), **(target.overrides or {})}
        return FilterSpec(**merged)


def load_config(path: str | Path = "config.yaml") -> Config:
    """config.yaml 로드·검증. 파일이 없으면 명확한 에러."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {p.resolve()}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config.model_validate(data)
