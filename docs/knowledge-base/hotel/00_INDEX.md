# 酒店差旅业务知识库 索引

## 1. 适用范围

本知识库面向"差旅政策问答 / Travel Ops Copilot"场景，覆盖企业差旅中酒店相关的全链路业务：选品 → 预订 → 入住 → 异常处理 → 结算 → 报销 → 合规。所有文档面向中国境内企业差旅运营、海外差旅、混合云酒店供应链场景。

## 2. 使用建议

- 上传到 `知识库管理` 时，**租户 ID** 与 **客户 ID** 推荐与该文档涉及的对象一致；通用规则文档（如术语表）可使用 `default` / `__shared__`。
- 文档之间通过相对链接互相引用，RAG 检索引用时尽量保留章节标题。
- 每份文档头部都有 `#### 关键词` 区域，方便检索召回。
- 决策表 / 表格段落是 RAG 高价值召回区，请勿改成自由文段。

## 3. 目录

| 编号 | 文档 | 内容 |
| --- | --- | --- |
| 01 | [行业概览与酒店分类](01_industry_overview.md) | 国标星级 / 国际评级 / 商务 / 经济 / 精选服务 / 度假 / 民宿 |
| 02 | [术语表（中英对照）](02_glossary.md) | 酒店、差旅、渠道、税务、支付、运营常用术语 |
| 03 | [房型与床型规范](03_room_types_and_bedding.md) | 房型代码、床型、加床、入住人数 |
| 04 | [房价与费用结构](04_rate_plans_and_fees.md) | 价格码、含早、套餐、resort fee、税费分项 |
| 05 | [渠道与分销](05_distribution_channels.md) | OTA / GDS / CRS / 批发商 / 直连 / 直销 |
| 06 | [预订全流程 SOP](06_booking_sop.md) | 报价 → 担保 → 出单 → 确认 → 入住 |
| 07 | [改签 / 取消 / 退款 SOP](07_modification_cancellation_sop.md) | 取消时段、违约金、扣款规则 |
| 08 | [No-show / 早离 / 迟到 SOP](08_noshow_earlycheckout_latecheckin_sop.md) | 异常入住场景处理 |
| 09 | [超售 / 换房 / Walk SOP](09_overbooking_walk_relocation_sop.md) | 超售识别、补救、换房升级 |
| 10 | [企业协议价与签约 SOP](10_corporate_rate_contract_sop.md) | RFP、协议价、LRA/NLRA、SLA |
| 11 | [结算与支付](11_settlement_and_payment.md) | 现付 / 预付 / 月结 / BTA / 信用账期 |
| 12 | [中国境内税务与发票](12_invoicing_tax_china.md) | 增值税、专票 / 普票、抬头、税号 |
| 13 | [海外税务与汇率](13_overseas_tax_and_fx.md) | VAT、occupancy tax、resort fee、汇兑 |
| 14 | [报销与差旅政策合规](14_reimbursement_compliance.md) | 标准、超标、违规处理 |
| 15 | [客诉与争议处理 SOP](15_complaint_handling_sop.md) | 客诉分级、补救、Chargeback |
| 16 | [不可抗力 / 应急 SOP](16_force_majeure_sop.md) | 自然灾害、疫情、战争、罢工 |
| 17 | [会员体系与企业项目](17_loyalty_programs.md) | Bonvoy/IHG One/Honors/World of Hyatt/Accor/华住/锦江/亚朵 |
| 18 | [数据接入与字段规范](18_data_integration_field_spec.md) | 字段映射、酒店 ID、价格码、状态码 |
| 19 | [合规与隐私安全](19_compliance_privacy_security.md) | 个保法 / GDPR / PCI-DSS / 公安备案 |
| 20 | [SLA、KPI 与运营指标](20_sla_kpi_metrics.md) | RevPAR/ADR/OCC、出票成功率、响应时效 |
| 21 | [FAQ](21_faq.md) | 高频问答 |
| 22 | [决策表速查](22_decision_tables.md) | 取消、退款、合规、补救等决策表 |

## 4. 关键词索引

`星级 / 房型 / 房价 / OTA / GDS / Booking / Expedia / Agoda / Ctrip / 携程 / 美团 / 飞猪 / 直连 / 协议价 / corporate rate / LRA / NLRA / RFP / 担保 / guarantee / 取消 / cancellation / no-show / 早离 / overbooking / 超售 / walk / 房费 / resort fee / city tax / occupancy tax / VAT / 增值税 / 专票 / 普票 / 月结 / BTA / virtual card / 报销 / 差标 / 超标 / 客诉 / 争议 / chargeback / 不可抗力 / 会员 / Bonvoy / IHG / Hilton Honors / Hyatt / Accor / 华住 / 锦江 / 亚朵 / 个保法 / PIPL / GDPR / PCI-DSS / RevPAR / ADR / OCC`
