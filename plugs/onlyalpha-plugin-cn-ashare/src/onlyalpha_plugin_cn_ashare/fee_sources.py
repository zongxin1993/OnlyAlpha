"""Auditable official-source identities for the CN A-share Market Fee Pack."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class OnlyCnAshareFeeAuthoritySource:
    source_id: str
    issuer: str
    document_id: str
    publication_date: date
    effective_date: date
    official_locator: str
    normalized_interpretation: str
    supporting_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_id,
                self.issuer,
                self.document_id,
                self.official_locator,
                self.normalized_interpretation,
            )
        ):
            raise ValueError("MARKET_FEE_SOURCE_INVALID")


_SH_INTERFACE = "CSDC:SH-SETTLEMENT-INTERFACE:V3.102"
_SZ_INTERFACE = "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17"

CN_A_SHARE_FEE_AUTHORITY_SOURCES = (
    OnlyCnAshareFeeAuthoritySource(
        "PRC-NPC:STAMP-TAX-LAW:2021",
        "全国人民代表大会常务委员会",
        "中华人民共和国主席令第八十九号",
        date(2021, 6, 10),
        date(2022, 7, 1),
        "https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html",
        "普通人民币 A 股证券交易印花税按成交金额向出让方征收。",
        (_SH_INTERFACE, _SZ_INTERFACE),
    ),
    OnlyCnAshareFeeAuthoritySource(
        "MOF-STA:ANNOUNCEMENT-2023-39:1",
        "财政部、国家税务总局",
        "财政部 税务总局公告2023年第39号",
        date(2023, 8, 27),
        date(2023, 8, 28),
        "https://jx.mof.gov.cn/xxgk/zhengcefagui/202309/t20230904_3905337.htm",
        "自 2023-08-28 起证券交易印花税减半至 0.5‰。",
        ("PRC-NPC:STAMP-TAX-LAW:2021", _SH_INTERFACE, _SZ_INTERFACE),
    ),
    OnlyCnAshareFeeAuthoritySource(
        "CSDC:SSE-FEE-TABLE:2025-06-30",
        "中国证券登记结算有限责任公司",
        "上海市场证券登记结算业务收费及代收税费一览表",
        date(2025, 6, 30),
        date(2025, 6, 30),
        "https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml",
        "上海市场 A 股交易过户费按成交金额 0.01‰ 向买卖双方收取。",
        (_SH_INTERFACE,),
    ),
    OnlyCnAshareFeeAuthoritySource(
        "CSDC:SZSE-FEE-TABLE:2025-06-30",
        "中国证券登记结算有限责任公司",
        "深圳市场证券登记结算业务收费及代收税费一览表",
        date(2025, 6, 30),
        date(2025, 6, 30),
        "https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml",
        "深圳市场普通 A 股交易过户费按成交金额 0.01‰ 向买卖双方收取。",
        (_SH_INTERFACE, _SZ_INTERFACE),
    ),
    OnlyCnAshareFeeAuthoritySource(
        _SH_INTERFACE,
        "中国证券登记结算有限责任公司上海分公司",
        "登记结算数据接口规范 V3.102",
        date(2026, 7, 17),
        date(2026, 7, 17),
        "https://www.chinaclear.cn/zdjs/jshsc/",
        "费用金额按人民币分精度传输。",
    ),
    OnlyCnAshareFeeAuthoritySource(
        _SZ_INTERFACE,
        "中国证券登记结算有限责任公司深圳分公司",
        "登记结算数据接口规范 Ver5.17",
        date(2026, 2, 2),
        date(2026, 2, 2),
        "https://www.chinaclear.cn/zdjs/jszsc/",
        "费用金额字段为两位小数人民币金额。",
    ),
)

CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID = {item.source_id: item for item in CN_A_SHARE_FEE_AUTHORITY_SOURCES}

__all__ = [
    "CN_A_SHARE_FEE_AUTHORITY_SOURCES",
    "CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID",
    "OnlyCnAshareFeeAuthoritySource",
]
