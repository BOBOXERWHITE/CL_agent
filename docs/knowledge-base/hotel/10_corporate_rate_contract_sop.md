# 10 企业协议价与签约 SOP

#### 关键词
`协议价 / Corporate Rate / Negotiated Rate / RFP / Request for Proposal / LRA / NLRA / Rate Loading / CRC / IATA / TMC / SLA / KPI / 续签 / Year-Round Rate / Project Rate`

## 1. 协议价模式分类

| 类型 | 含义 | 适用 |
| --- | --- | --- |
| Year-Round Rate | 全年固定折扣，淡旺季同价 | 高频差旅城市 |
| Dynamic Discount | 折扣率绑定 BAR 浮动（如 BAR -10%） | 大企业、深度博弈 |
| Tiered Rate | 按年度量级阶梯（10k 间夜 -5%，30k -8%） | 大型集团 |
| Project Rate | 项目阶段限时协议 | 工程 / 长驻项目 |
| Crew Rate | 机组 / 长期工作组协议 | 航司、施工 |
| Group Rate | ≥10 间夜 | MICE、培训 |
| Promotional Code | 限时折扣码 | 营销活动 |

## 2. 协议价的核心条款

### 2.1 必谈条款

| 条款 | 推荐内容 |
| --- | --- |
| 房价 | 明确房型 + 含早 + 服务费 + 税 |
| LRA | 明确末房可售（强烈建议） |
| 取消政策 | 入住当日 16:00–18:00 免费 |
| 担保政策 | 公司挂账 / Direct Bill / BTA |
| 早餐 | 双早 / 单早 / 不含早（明确） |
| Late Check-out | 14:00 / 16:00 |
| 行政待遇 | 行政酒廊 / 欢迎礼遇 |
| 升级政策 | 满足条件自动升 1 档 |
| Walk SLA | ≤2% Walk Rate，违反赔偿 |
| 月结账期 | 30 / 45 / 60 天 |
| 发票 | 增值税专票，月结 |
| 复议机制 | 季度业务复盘 |

### 2.2 SLA / KPI 例

| 指标 | 阈值 |
| --- | --- |
| 出单成功率 | ≥99% |
| Walk Rate | ≤2% |
| 客诉率 | ≤1% |
| 客诉响应时效 | ≤2h |
| 月结对账时效 | T+5 |
| 发票准时率 | ≥98% |
| RFP 价格变动通知 | 提前 30 天书面 |

## 3. RFP 周期（年度）

```
[8 月]   差旅采购数据汇总（去年间夜量、ADR、城市分布、酒店清单）
[9 月]   筛选目标酒店 / 集团（含新增）
[9 月]   发出 RFP（标准模板 + 公司差旅政策）
[10 月]  酒店报价回收
[10 月]  比价 / 价格 + 服务双轴评估
[11 月]  复盘 / 反报价
[11 月]  签约 / Rate Loading
[12 月]  TMC / GDS / OBT 上线测试
[1 月]   全员推送新协议
[Q+季度] 业务复盘 + 调整
```

### 3.1 RFP 模板字段

```yaml
company_profile:
  legal_name: string
  industry: string
  annual_revenue: number
  annual_travel_spend: number
  annual_room_nights: number
  major_cities: [city]
  cc_program: BCD/Amex/Concur/Egencia/...
hotel_request:
  city: string
  preferred_brands: [brand]
  star_min: 3
  required_amenities: [free_wifi, gym, breakfast, ...]
  required_room_types: [standard_king, standard_twin, exec_king]
  estimated_room_nights: number
  loyalty_program_required: bool
hotel_response:
  accepted: bool
  proposed_rate: number
  rate_includes_breakfast: bool
  rate_includes_taxes: bool
  rate_includes_service_charge: bool
  resort_fee: number
  lra_guarantee: bool
  cancel_policy: 6pm same day | 24h | 48h | other
  late_checkout: 12pm | 2pm | 4pm
  upgrade_policy: string
  free_wifi: bool
  parking: included|excluded|charged
  walking_sla: ≤X%
  monthly_settlement: bool
  settlement_terms: net 30|45|60
  invoice_type: 增值税专票|普票|海外发票
  vat_registration_id: string
```

### 3.2 比价评分模型

```
total_score =
    0.40 × 价格分（与目标价对比）
  + 0.20 × 服务分（含早 / 升级 / 行政待遇 / 健身房 / 商务中心）
  + 0.15 × 区位分（距客户公司 / 机场距离）
  + 0.10 × 历史满意度（公司过去入住分）
  + 0.10 × LRA / 月结 / 发票（合规分）
  + 0.05 × 品牌 / 会员价值
```

## 4. 协议价加载（Rate Loading）

```
1. 集团 CRS Loading
   Marriott / Hilton / IHG / Hyatt / Accor / 华住 / 锦江 / Shangri-La 在
   集团 CRS 录入 SET 号（SET ID / Corporate Account Code）

2. GDS Loading
   通过 SynXis / Travelport / Sabre / Amadeus / TravelClick 加载
   公司 IATA / CRC 代码 → 同步到所有 GDS

3. TMC OBT 加载
   Concur / Egencia / 携程商旅 / BCD Travel / Amex GBT / Cytric

4. 直连酒店内部 PMS Loading
   Opera / Marsha / OnQ 内部录入

5. 测试预订
   每个城市抽 1 家测试出单 + 现场入住
```

### 4.1 常见加载错误

| 错误 | 处理 |
| --- | --- |
| 加载到错误的 IATA 号 | 立即更正，否则 OTA 加价 |
| 未启用 LRA | 节假日协议价被关闭 |
| 含早未启用 | 入住时酒店收早餐费 |
| 城市错配 | 协议价被错误下放到非协议酒店 |
| Loading 滞后 | 1 月 1 日前加载完毕，否则前几天按 BAR |

## 5. 续签策略

### 5.1 续签触发

```
[2026-08]  收集去年数据
[2026-09]  评估 KPI / SLA / Walk / 客诉
[2026-10]  与销售经理对账
[2026-11]  发起续签 / 重谈
[2026-12]  签订新合同
```

### 5.2 续签筹码

| 谈判要点 | 增筹码 |
| --- | --- |
| 增加间夜 | 折扣加深 |
| 增加品牌联谊 | 行政酒廊 / 升级 |
| 长账期 → 短账期 | 折扣再降 |
| 月结改预付 | 折扣再降 |
| 多城打包 | 集团整体折扣 |
| Walk 历史多 | 罚则加严 |

### 5.3 退出 (Walk-away)

- 酒店年内 Walk Rate >2%
- 客诉率 >2%
- 价格回调 >5%
- 集团变更政策（如取消 LRA）
- 该酒店关停 / 翻新

## 6. 协议价的运营治理

### 6.1 角色

| 角色 | 职责 |
| --- | --- |
| 差旅采购 (Travel Procurement) | RFP / 谈判 / 续签 |
| 财务 (Finance) | 预算、月结、发票 |
| HRBP / 行政 | 政策落地、员工培训 |
| TMC / OBT | 系统对接、实际出单 |
| 业务 / 项目 | 提供差旅需求 |
| 安全 / 合规 | 风控、目的地评估 |

### 6.2 数据看板

```
1. 协议覆盖率：协议出单数 / 总出单数（目标 ≥70%）
2. 协议遵从率：协议出单的差标合规 / 总（目标 ≥95%）
3. 平均房价 (ADR)
4. 同城基准比 (vs 市场 ADR / RFP 报价)
5. Walk Rate
6. 客诉率
7. 月结对账延迟
8. 发票合规率
```

## 7. 国内 vs 国际差异

| 维度 | 国内 | 国际 |
| --- | --- | --- |
| 谈判周期 | 9–12 月 | 9–11 月 |
| 锚定货币 | RMB | USD / EUR / 本币 |
| LRA | 谈判项 | 多数标配 |
| 月结 | 普遍 | 普遍（外企） |
| 发票 | 增值税专票 / 普票 | VAT Invoice / Receipt |
| 集团 RFP 平台 | 携程商旅 / 美团商旅 | HRS / BCD / Amex GBT / Lanyon |
| Loading 周期 | 30 天 | 30–60 天 |
| 月结账期 | 30 天 | 30–60 天 |
| 担保 | 公司挂账 | BTA / VCC / Direct Bill |

## 8. 决策表（员工层）

| 场景 | 推荐 |
| --- | --- |
| 协议价命中 + 含早 + 月结 | **首选** |
| 协议价命中但不含早 | 次选（再评估） |
| 协议价命中但 NLRA + 高峰期 | 备选（可能被关闭） |
| 协议价未命中（同城无协议） | BAR + 早鸟 |
| 协议价高于 BAR | **拒用** + 反馈给采购 |

## 9. 谈判常见话术与盲区

### 9.1 必问问题

```
Q: LRA 是否覆盖所有房型？
Q: 协议价 = 不含早还是含早？份数？
Q: 有否 Resort Fee / 服务费 / 杂费？
Q: 取消政策具体到几点？
Q: Walk SLA 是否成文，违反后赔偿？
Q: 行政酒廊待遇覆盖哪些房型 / 客层？
Q: 月结账期是 30 还是 45？
Q: 发票格式（专票 / 普票 / 海外 VAT）？
Q: 协议覆盖整个集团（连锁）还是仅本店？
Q: 折扣是固定还是 BAR 联动？
Q: 如何在 GDS / OBT / OTA 加载？
```

### 9.2 隐藏成本

```
- 行政酒廊只对 Exec 房型免费，标房需付 RMB 200 / 人 / 晚
- 含早份数 = 1 份（不是 2）
- 服务费另算 10%
- Resort Fee 另收 RMB 100 / 晚
- Wi-Fi 高速版另算 USD 15 / 晚
- 周末加价 +10%
- 节假日 (春节 / 五一 / 国庆 / 圣诞) 协议价关闭
- 城市税 / 旅游税另算
```

## 10. 与其他章节的关系

- 价格码：[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- 渠道：[05_distribution_channels.md](05_distribution_channels.md)
- 月结 / 财务：[11_settlement_and_payment.md](11_settlement_and_payment.md)
- 发票：[12_invoicing_tax_china.md](12_invoicing_tax_china.md)
- KPI：[20_sla_kpi_metrics.md](20_sla_kpi_metrics.md)
