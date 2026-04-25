# 13 海外税务与汇率

#### 关键词
`VAT / GST / Occupancy Tax / Resort Fee / Destination Fee / City Tax / Service Charge / Tourist Tax / 退税 / VAT Refund / DCC / Dynamic Currency Conversion / FX / 汇率 / 换汇 / 跨境支付`

## 1. 海外税务总览

| 国家 / 地区 | 主要税种 | 名称 | 税率（住宿） | 备注 |
| --- | --- | --- | --- | --- |
| 美国 | Sales Tax + Occupancy Tax | 各州 / 市分别征 | 总额 8–18% | 各州差异巨大 |
| 加拿大 | GST + PST + 省税 | GST/HST | 5–15% | 安大略 13% |
| 英国 | VAT | VAT | 20%（含在房价） | 标房一般含 |
| 法国 | VAT + Taxe de Séjour | VAT 10% | 10% + 旅游税按人 / 晚 |  |
| 德国 | VAT + City Tax | VAT 7% | 7% + 5% 城市税 | 商务可豁免 City Tax |
| 意大利 | IVA + Tassa di Soggiorno | 10% | 10% IVA + 旅游税 |  |
| 西班牙 | IVA + Tasa Turística | 10% | IVA + 旅游税 |  |
| 葡萄牙 | IVA + Taxa Municipal | 6% | 加 EUR 1–2 / 晚 |  |
| 荷兰 | BTW + Toeristenbelasting | 9% | + 12.5% 旅游税 |  |
| 比利时 | TVA + 城市税 | 6% | 含旅游税 |  |
| 瑞士 | MWST/TVA + Kurtaxe | 3.7%（住宿） | 较低，但额外 city kurtaxe |  |
| 奥地利 | USt | 10% | 通常含 |  |
| 日本 | 消费税 + 宿泊税 | 10% | 部分城市加 JPY 100–500 / 晚 |  |
| 韩国 | VAT | 10% | 通常含在房价 |  |
| 新加坡 | GST + Service Charge | GST 9% | 加 10% 服务费 |  |
| 泰国 | VAT | 7% | 加 10% 服务费 |  |
| 越南 | VAT | 10% | 加 5% 服务费 |  |
| 印度 | GST | 12% / 18% | 房价 ≤7,500 INR 12%；更高 18% |  |
| 印尼 | VAT + 服务费 | 11% + 21%（含税服务费） |  |
| 马来西亚 | SST + Tourism Tax | 6%（SST） | + RM 10 / 晚（外籍） |  |
| 菲律宾 | VAT + 服务费 | 12% | + 10% 服务费 |  |
| 阿联酋 | VAT + Tourism Dirham | 5% | 不同酋长国地方税 |  |
| 土耳其 | KDV | 8% | 加旅游费 2% |  |
| 澳大利亚 | GST | 10% | 含税 |  |
| 新西兰 | GST | 15% | 含税 |  |
| 巴西 | ISS + 服务费 | 5% | + 10% 服务费 |  |
| 阿根廷 | IVA | 21% | 跨境支付时部分可豁免 |  |
| 墨西哥 | IVA + Lodging Tax | 16% | + 2–3% 城市 |  |
| 俄罗斯 | НДС | 0%（2027 年前住宿免税） |  | 优惠政策延续 |
| 香港 | 无 GST/VAT | — | 0% | 房价为净价 |
| 澳门 | 旅游税 | 5% | 加 10% 服务费 |  |
| 台湾 | 营业税 | 5% | 含在房价 |  |

## 2. 美国住宿税细节

美国住宿税由"州 + 县 + 市"叠加，差异巨大：

| 城市 | 总税率（含 Sales + Occupancy） | 备注 |
| --- | --- | --- |
| 纽约 | 14.75% + USD 3.50 / 晚 (Convention) | 高 |
| 旧金山 | 14% + 城市设施税 |  |
| 拉斯维加斯 (Strip) | 13.38% + USD 39 Resort Fee | + Resort Fee 单独 13.38% |
| 洛杉矶 | 14% |  |
| 迈阿密 | 13% + Convention Tax |  |
| 芝加哥 | 17.4% | 极高 |
| 西雅图 | 15.6% |  |
| 波士顿 | 14.95% |  |
| 华盛顿 DC | 14.95% |  |
| 奥斯汀 | 17% |  |
| 夏威夷 | 17.962% (TAT + GET) |  |
| 拉斯维加斯下城 | 13% + USD 19 Resort Fee |  |

> **关键风险**：OTA 排序按 `nightly rate + tax`，**不含 Resort Fee**。员工以为 BAR 99 + 14% = 113，实际入住时还要付 USD 39 Resort Fee + 5.22 Resort Fee Tax = USD 158。差旅平台必须在卡片显示 `mandatory_surcharges`。

## 3. Resort Fee / Destination Fee

| 收费项 | 城市 | 典型金额 |
| --- | --- | --- |
| Resort Fee | Las Vegas / Honolulu / Miami / Cancun | USD 25–45 / 晚 |
| Destination Fee | New York / Las Vegas / Chicago | USD 25–35 / 晚 |
| Amenity Fee | Boutique 酒店 | USD 10–25 / 晚 |
| Urban Fee | 大城市 | USD 10–30 / 晚 |
| Tourism Fee | Dubai / Abu Dhabi | AED 10–20 / 晚 |
| Spa Tax | Hot Springs / 度假村 | 视州 |

含的服务一般包括：

- Wi-Fi
- 健身房
- 报纸
- 本地通话
- 部分早餐 / 饮料 / 咖啡
- 游泳池 / 桑拿
- 行李寄存
- 入住快速通道

> **不可抗议**（除非欺诈）：除非 OTA 隐藏，否则 Resort Fee 通常作为"必收强制项"，无法免除。

## 4. 欧洲城市税（Tourist Tax）

按"星级 × 人数 × 晚数"分级：

| 城市 | 计费方式 | 典型范围 |
| --- | --- | --- |
| 巴黎 | 按星级 + 人 + 晚 | EUR 0.65–14.95 / 人 / 晚 |
| 罗马 | 按星级 + 人 + 晚 | EUR 3.5–10 |
| 米兰 | 按星级 + 人 + 晚 | EUR 2–7 |
| 巴塞罗那 | 按星级 + 人 + 晚 | EUR 2.5–7.5 |
| 马德里 | 按星级 + 人 + 晚 | EUR 0.15–3 |
| 柏林 | 5% × 房费 | 商务可豁免 |
| 慕尼黑 | 0% | 无 |
| 阿姆斯特丹 | 12.5% × 房费 + EUR 3 / 人 / 晚 | 高 |
| 维也纳 | 3.2% × 房费 |  |
| 苏黎世 | CHF 2.5 / 人 / 晚 |  |
| 布拉格 | CZK 50 / 人 / 晚 |  |
| 哥本哈根 | 无 | 不征 |
| 斯德哥尔摩 | 无 |  |
| 莫斯科 | 无 |  |
| 伊斯坦布尔 | 2% (KDV) |  |

## 5. 服务费 (Service Charge)

| 国家 | 是否强制 | 典型 |
| --- | --- | --- |
| 美国 | 多数无（有也可拒） | 0–5% |
| 欧洲 | 包含在房价 | 已含 |
| 中东 | 强制 | 10–15% |
| 东南亚 | 多数强制 | 10% |
| 日本 | 高端酒店 | 10–15% |
| 中国大陆 | 视酒店 | 5–15% |
| 香港 | 强制 | 10% |
| 台湾 | 强制 | 10% |

> 服务费**先于税**计算："房价 × (1 + 10% 服务费) × (1 + 7% VAT)"。员工常误以为可叠加直加，实际比例更高。

## 6. VAT 退税（出境差旅）

### 6.1 适用范围

部分国家允许非居民出境时退还住宿 VAT，但**多数国家仅退商品 VAT，住宿 VAT 不退**。少数例外：

| 国家 | 是否退住宿 VAT | 备注 |
| --- | --- | --- |
| 欧盟 | 否（住宿不退） | 仅商品 |
| 英国 | 否（脱欧后无退税） |  |
| 日本 | 否 | 仅免税商品 |
| 韩国 | 否（住宿） | 商品退税 |
| 泰国 | 否 |  |
| 新加坡 | 否 | GST 仅退商品 |
| 阿联酋 | 否 |  |
| 澳大利亚 | 否 |  |

> **企业差旅 VAT 退税**：欧盟 13th Directive 与 8th Directive 允许非欧盟企业 / 欧盟跨境企业申请退还商务用 VAT。流程长（6–12 个月），通常委托第三方（VAT IT、Taxback、ASD Group）。

### 6.2 申请所需材料

```
- 公司注册证明（VAT 编号或等价 ID）
- 原始 VAT 发票（正本）
- 入住凭证 / Folio
- 公务证明（项目函、客户邀请函）
- 签证页 / 入境章
- 银行账户（接收外汇）
```

## 7. 汇率与跨境支付

### 7.1 汇率类型

| 类型 | 来源 | 用途 |
| --- | --- | --- |
| 中间价 | 央行公布 | 参考 |
| 银行现汇买入价 | 银行 | 收外币 |
| 银行现汇卖出价 | 银行 | 购汇 |
| 卡组织汇率 | Visa / Mastercard / UnionPay / Amex | 信用卡结算 |
| OTA 显示汇率 | OTA | 营销 / 排序 |

### 7.2 信用卡跨境结算

```
1. 持卡人在海外刷卡（USD）
2. 收单行结算给 Visa / Mastercard（USD）
3. Visa / Mastercard 按其汇率换为持卡人本币（RMB）
4. 部分卡发行行加 1–2% 跨境手续费
```

> 银行卡跨境手续费可达 1.5–3%，差旅政策应推荐**多币种公司卡 (BTA / VCC)**降低手续费。

### 7.3 DCC (Dynamic Currency Conversion)

收单行 / POS 自动询问"以本币 (RMB) 还是当地币 (USD) 结算"：

| 选择 | 优点 | 缺点 |
| --- | --- | --- |
| 当地币 (USD) | 银行 / 卡组织汇率，公道 | 不知具体金额 |
| 本币 (RMB) | 当时可知金额 | DCC 加价 1–10% |

> **永远选择当地币**，DCC 加价是隐性成本。

### 7.4 大额跨境结算

| 方式 | 适用 |
| --- | --- |
| 信用卡 | ≤USD 5,000 / 笔 |
| 公司 BTA / Lodge Card | 中等 |
| 跨境电汇 (T/T) | 大额 |
| 国际结算账户 | 长期合作 |
| Western Union | 不推荐（手续费高） |
| 数字稳定币 (USDT/USDC) | 不合规 |

## 8. 含税 / 不含税表达差异

| 表达 | 含义 |
| --- | --- |
| Per night | 每晚（不含税，多数美国） |
| Per stay | 整段（不含税） |
| Per person | 每人（含早 / 全包） |
| All-in / Total / Inclusive | 含全部税费 |
| Net of tax | 不含税 |
| Plus tax | 加税（要补加） |
| Plus plus (++) | 加服务费 + 加税 |
| Single plus (+) | 加服务费 |
| Net rate | 净价（B2B） |

## 9. 差旅政策建议

```
[1] 海外报价显示"全部含 + 强制项"
[2] 全包价分项展示：Room / Tax / Resort Fee / Service / Wifi / Parking
[3] 预算管控按 "全部含税" 总额
[4] 选币种时坚持当地币
[5] DCC 默认拒绝
[6] 大额结算走公司账户
[7] 月结对账每个酒店分国家货币
```

## 10. 差旅平台技术字段建议

```yaml
overseas_pricing:
  base_currency: "USD"
  base_rate_per_night: 199.00
  taxes:
    - name: "Sales Tax"
      rate_pct: 0.0825
      amount: 16.42
    - name: "Occupancy Tax"
      rate_pct: 0.0513
      amount: 10.21
  mandatory_surcharges:
    - name: "Resort Fee"
      per_night: 39.00
      taxable: true
      tax_rate_pct: 0.1338
      tax_amount_per_night: 5.22
    - name: "Destination Fee"
      per_night: 0
  total_per_night_inclusive: 269.85
  total_stay_inclusive: 1349.25  # 5 晚
  fx:
    quoted_rate_to_local: 7.20  # 锁定汇率
    quoted_at_utc: timestamp
    estimated_cny_amount: 9714.60
```

## 11. 风险点

1. **OTA 显示价 vs 实际价**：必查 `mandatory_surcharges`，避免员工误算
2. **Resort Fee 课税基**：少数州把 Resort Fee 也课税，整段总额比表面高 5%
3. **DCC 默认勾选**：部分酒店 POS 默认 DCC，员工需主动拒绝
4. **跨境信用卡手续费**：超过 3% 应换 BTA / VCC
5. **欧盟商务税豁免**：部分德 / 法城市企业可豁免 City Tax，但需出示公务证明
6. **东南亚不开 VAT 发票**：仅 Receipt，进项税不可抵扣
7. **现金支付**：海外大额现金支付涉及反洗钱，避免
8. **海外退款时长**：部分国家需 30 工作日以上

## 12. 与其他章节的关系

- 国内税务：[12_invoicing_tax_china.md](12_invoicing_tax_china.md)
- 月结 / 跨境支付：[11_settlement_and_payment.md](11_settlement_and_payment.md)
- 报销合规：[14_reimbursement_compliance.md](14_reimbursement_compliance.md)
- 价格码 / Resort Fee：[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
