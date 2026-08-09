"""Auditable official sources for the production China A-share fee pack."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class OnlyFeeAuthoritySourceRecord:
    source_id: str
    issuer: str
    document_id: str
    title: str
    publication_date: date
    effective_date: date
    official_locator: str
    scope: str
    normalized_interpretation: str
    supporting_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_id,
                self.issuer,
                self.document_id,
                self.title,
                self.official_locator,
                self.scope,
                self.normalized_interpretation,
            )
        ):
            raise ValueError("MARKET_FEE_SOURCE_INVALID")


CN_A_SHARE_FEE_AUTHORITY_SOURCES = (
    OnlyFeeAuthoritySourceRecord(
        "PRC-NPC:STAMP-TAX-LAW:2021",
        "全国人民代表大会常务委员会",
        "中华人民共和国主席令第八十九号",
        "中华人民共和国印花税法",
        date(2021, 6, 10),
        date(2022, 7, 1),
        "https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html",
        "依法设立的证券交易所内股票交易；向出让方征收；计税依据为成交金额",
        "普通人民币 A 股集中交易的证券交易印花税按成交金额计税，仅适用于 SELL。",
        (
            "CSDC:SH-SETTLEMENT-INTERFACE:V3.102",
            "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17",
        ),
    ),
    OnlyFeeAuthoritySourceRecord(
        "MOF-STA:ANNOUNCEMENT-2023-39:1",
        "财政部、国家税务总局",
        "财政部 税务总局公告2023年第39号",
        "关于减半征收证券交易印花税的公告",
        date(2023, 8, 27),
        date(2023, 8, 28),
        "https://jx.mof.gov.cn/xxgk/zhengcefagui/202309/t20230904_3905337.htm",
        "证券交易印花税",
        "自 2023-08-28 起将印花税法规定的 1‰ 证券交易印花税减半为 0.5‰。",
        (
            "PRC-NPC:STAMP-TAX-LAW:2021",
            "CSDC:SH-SETTLEMENT-INTERFACE:V3.102",
            "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17",
        ),
    ),
    OnlyFeeAuthoritySourceRecord(
        "CSDC:SSE-FEE-TABLE:2025-06-30",
        "中国证券登记结算有限责任公司",
        "上海市场证券登记结算业务收费及代收税费一览表（2025年6月30日更新）",
        "上海市场证券登记结算业务收费及代收税费一览表",
        date(2025, 6, 30),
        date(2025, 6, 30),
        "https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml",
        "上海市场 A 股交易过户费",
        "A 股交易过户费按成交金额 0.01‰ 向买卖双方收取。",
        ("CSDC:SH-SETTLEMENT-INTERFACE:V3.102",),
    ),
    OnlyFeeAuthoritySourceRecord(
        "CSDC:SZSE-FEE-TABLE:2025-06-30",
        "中国证券登记结算有限责任公司",
        "深圳市场证券登记结算业务收费及代收税费一览表（2025年6月30日更新）",
        "深圳市场证券登记结算业务收费及代收税费一览表",
        date(2025, 6, 30),
        date(2025, 6, 30),
        "https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml",
        "深圳市场 A 股交易过户费（不含综合协议交易平台）",
        "普通 A 股集中交易过户费按成交金额 0.01‰ 向买卖双方收取。",
        (
            "CSDC:SH-SETTLEMENT-INTERFACE:V3.102",
            "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17",
        ),
    ),
    OnlyFeeAuthoritySourceRecord(
        "CSDC:SH-SETTLEMENT-INTERFACE:V3.102",
        "中国证券登记结算有限责任公司上海分公司",
        "中国结算沪-JS-KFB-JKGF-01-2026/E",
        "登记结算数据接口规范（结算参与人版V3.102）",
        date(2026, 7, 17),
        date(2026, 7, 17),
        "https://www.chinaclear.cn/zdjs/jshsc/202607/03060adf303a42009724bf4e2e6ec6f0/files/登记结算数据接口规范（结算参与人版V3.102）.pdf",
        "上海市场结算参与人登记结算数据中的人民币费用金额字段",
        "印花税和过户费字段以两位小数金额传输；规范内金额计算规则使用四舍五入保留两位小数。",
    ),
    OnlyFeeAuthoritySourceRecord(
        "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17",
        "中国证券登记结算有限责任公司深圳分公司",
        "深市登记结算数据接口规范（结算参与人版Ver5.17）",
        "深市登记结算数据接口规范（结算参与人版Ver5.17）",
        date(2026, 2, 2),
        date(2026, 2, 2),
        "https://www.chinaclear.cn/zdjs/jszsc/202601/1b4d49fa0dcb4385bdc47295723b5ccf/files/深市登记结算数据接口规范（结算参与人版Ver5.17）.pdf",
        "深圳市场结算参与人登记结算数据中的人民币费用金额字段",
        "印花税和过户费字段为 N(12,2)，确认生产费用金额的人民币分精度。",
    ),
)

CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID = {item.source_id: item for item in CN_A_SHARE_FEE_AUTHORITY_SOURCES}


__all__ = [
    "CN_A_SHARE_FEE_AUTHORITY_SOURCES",
    "CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID",
    "OnlyFeeAuthoritySourceRecord",
]
