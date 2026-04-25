# 04 房价与费用结构

#### 关键词
`房价 / 价格码 / Rate Code / Rate Plan / BAR / RACK / 协议价 / 含早 / 含税 / 服务费 / 城市税 / Resort Fee / Destination Fee / Occupancy Tax / VAT / GST / 押金 / 担保 / 套餐 / Package / 退改政策 / 取消政策 / 限时促销 / 早鸟 / 连住 / 提前预订`

## 1. 房价层级模型

差旅系统中应理解"价格 = 价格码 (Rate Code) + 价格结构 (Rate Structure) + 限制 (Restrictions) + 政策 (Policy)"。

```
RateCode  │ 例：BAR / CRP123 / PROMO20 / GOV / AAA
Structure │ 单价 / 折扣 / 套餐 / 含早 / 含 SPA
Restrictions │ MinLOS / CTA / CTD / 提前 N 日 / 仅会员 / 仅移动端
Policy    │ 取消政策 / 担保政策 / 押金 / 改签
Tax       │ 含 / 不含 / 服务费 / 城市税 / Resort Fee
```

## 2. 主流价格码（Rate Codes）

| 类型 | 价格码 | 折扣 / 特征 | 适用 |
| --- | --- | --- | --- |
| 门市价 | RACK | 无折扣，仅作参考 | 客诉补偿、Walk 计价 |
| 最优可售价 | BAR / BAR1 / BAR2 / BAR3 | 动态浮动，与 LRA 联动 | 个人差旅默认 |
| 早鸟价 | ADV / EARLY / NRF7 / NRF14 / NRF21 | 提前 7/14/21 日，多数不可退改 | 节省 8–25% |
| 连住价 | LOS3 / LOS5 / LOS7 / WEEKLY | 连续 3/5/7 晚 | 长差旅 |
| 含早价 | BB / BAR-BB | 比 BAR 高 5–10% | 默认含双早 |
| 含晚价 | DBL / DINNER | 含 1 晚餐 |  |
| 半膳价 | HB / MAP | 含早 + 1 正餐 | 度假村常见 |
| 全膳价 | FB / AP | 含三餐 | 度假村 / 偏远 |
| 全包价 | AI | 含餐 + 部分活动 | All-inclusive 度假村 |
| 协议价 | CRP / NEG / COMPANYCODE | 企业谈判价 | 企业差旅 |
| 政府价 | GOV / GSA | 政府差旅 | 政府客 |
| 长者价 | SR / SENIOR | 60/65 岁以上 |  |
| 协会价 | AAA / AARP / IATA / CAA | 凭会员卡 |  |
| 机组价 | CREW / AIRLINE | 航空机组 |  |
| 政府日补 | PER DIEM | GSA 标准 |  |
| 移动端 | MOBILE / APP | APP / 小程序 |  |
| 会员价 | MEMBER / MGR | 与 BAR 价差 5–10% | Marriott / Hilton / IHG / Hyatt |
| 不透明价 | OPAQUE | 隐藏品牌 (Hotwire / Priceline) |  |
| 套餐 | PKG / SPA / GOLF | 含活动 |  |
| 团体价 | GRP / GROUP | ≥10 间夜 |  |

## 3. 退改政策结构（Policy）

| 政策类型 | 字段 | 含义 |
| --- | --- | --- |
| 免费取消窗口 | `free_cancel_until` | UTC 时间，过此点收费 |
| 取消违约金 | `cancel_fee_after` | 金额 / 百分比 / 首晚 |
| 违约阶梯 | `cancel_tiers[]` | 距入住 X 小时 → 罚 Y |
| 是否可退 | `refundable` | true/false |
| 是否可改 | `modifiable` | true/false |
| 是否担保 | `guarantee_required` | 信用卡 / 现金 / 公司 |
| 押金 | `deposit_amount` | 含 / 不含税 |
| No-Show 政策 | `noshow_fee` | 通常 = 首晚房费 + 税 |
| 早离政策 | `early_departure_fee` | 通常 = 首晚 OR 全程房费 |

### 3.1 典型政策模式

| 模式 | 简称 | 取消窗口 | 退款 | 适用 |
| --- | --- | --- | --- | --- |
| 完全免费取消 | FRD / FullyRefundable | 入住前 24/48/72h 免费 | 全额 | 灵活差旅 |
| 限时免费取消 | Flex Until X | 至签到 X 日 | 全额 | 早期免费 / 临近收费 |
| 部分退款 | Semi-Refundable | 收首晚或 50% | 部分 |  |
| 不可退不可改 | NRF / Non-Refundable | 立即扣款 | 0 | 早鸟 / 促销 |
| 完全预付 | Prepaid / Advance Purchase | 立即扣款 | 见具体 |  |
| 免费但需担保 | Free Cancel + CCG | 免费 / 需信用卡 | — | 大多数 BAR |

### 3.2 取消违约阶梯示例

```
距入住 ≥ 72 h        免费
72 h > 距入住 ≥ 24 h  收 1 晚房费 + 税
< 24 h               收全程房费 + 税
未到 (No-Show)       收全程房费 + 税
```

> **注意**：海外取消时间多以**酒店当地时间**为准，国内多以**24:00 (UTC+8)** 为锚点。差旅系统应明确 `cancel_deadline_timezone`。

## 4. 含税 / 不含税 与税费分项

### 4.1 中国境内典型构成

```
房价 (含税基础)
  ├─ 房费 (Room Charge) — 适用增值税 6%（小规模 1%/3%）或 9%（住宿适用税率）
  ├─ 服务费 (Service Charge) — 一般 10–15%（高星级），与房费一并计税
  ├─ 政府基金 (Construction Fund) — 多数已废止
  └─ 增值税 (VAT) — 一般 6%
```

> 中国住宿服务一般纳税人增值税率：**6%（生活服务-住宿服务）**。简易计税 / 小规模纳税人为 3% 或 1%（疫情减免延续）。
> 部分 OTA / 携程"含税" = 房价 + VAT；"不含早" = 不含 BB；务必区分。

### 4.2 海外典型构成（美国 Las Vegas 为例）

```
房价 (Room Rate)
  ├─ Room Tax / Occupancy Tax 13.38%
  ├─ Resort Fee USD 39 / 晚 (强制，但**不计入** OTA 排序所用 Total)
  ├─ Resort Fee Tax 13.38% × Resort Fee
  └─ Destination Fee（部分酒店）
```

### 4.3 海外典型（欧洲）

| 国家 / 城市 | 项目 | 税率 |
| --- | --- | --- |
| 法国 巴黎 | Taxe de Séjour | EUR 0.65–14.95 / 人 / 晚（按星级） |
| 法国 巴黎 | VAT | 10% (住宿) |
| 意大利 罗马 | Tassa di Soggiorno | EUR 3.5–10 / 人 / 晚 |
| 西班牙 巴塞罗那 | Tasa Turística | EUR 2.5–7.50 / 人 / 晚 |
| 德国 柏林 | City Tax | 5% × 住宿费 |
| 英国 伦敦 | VAT | 20%（含在房价） |
| 荷兰 阿姆斯特丹 | Tourist Tax | 12.5% |
| 日本 东京 | 宿泊税 | JPY 100–200 / 晚（房价 ≥ 10,000 才征） |
| 韩国 首尔 | VAT | 10% |
| 泰国 曼谷 | VAT + 服务费 | 7% + 10% |

> 关于税务详情见 [13_overseas_tax_and_fx.md](13_overseas_tax_and_fx.md)。

## 5. 套餐与附加价值（Package）

### 5.1 套餐组成

| 套餐组件 | 字段 | 备注 |
| --- | --- | --- |
| 早餐 | `breakfast_count` | 1/2/3 份 |
| 午餐 / 晚餐 | `lunch_count`, `dinner_count` |  |
| 接送机 | `airport_transfer` | 单 / 双向 |
| 行政酒廊 | `executive_lounge` | 含 happy hour |
| SPA | `spa_credit` | 抵扣额度 |
| 高尔夫 | `golf_round` | 几洞 |
| 主题乐园门票 | `theme_park_ticket` | 名称 + 张数 |
| 房内迷你吧 | `minibar_credit` | 抵扣额度 |
| 洗衣 | `laundry_credit` |  |
| Late check-out | `late_checkout` | 至 14:00/16:00/18:00 |
| 早鸟早入 | `early_checkin_guaranteed` |  |

### 5.2 套餐定价规则

- **不可拆分**：套餐价不可单独取消其中组件
- **无重复优惠**：套餐不可叠加会员价 / 协议价 / 优惠券
- **取消时**：通常按"套餐总价"扣罚，不分项退款
- **报销时**：发票通常合并开具"住宿费"，但**含餐 / SPA 部分可能不在差旅报销范围内**，需差旅政策另行规定（见 [14_reimbursement_compliance.md](14_reimbursement_compliance.md)）

## 6. 含早结构

| 描述 | 含义 |
| --- | --- |
| Room Only / EP | 不含早 |
| BB / 含早 | 含早，份数 = 入住成人数（一般 ≤2） |
| 双早 | 2 份早 |
| 单早 | 1 份早 |
| 自助早 | Buffet（多数三星以上） |
| 套餐早 | A la carte（中低端 / 民宿） |
| 房内送餐早 | In-room dining（含服务费） |

> **关键风控点**：
> - 客户付的是 BB（含早），酒店分配单早 → 客诉 + 服务补救
> - 早餐免费年龄差异：12 岁以下、6 岁以下、3 岁以下分别有酒店采用，需逐酒店字段化
> - "含早" 是按"间夜含早"还是"按入住人数含早"，差旅政策需明确

## 7. 强制性 / 不计入房价的收费（Mandatory Surcharges）

OTA / 元搜索按"Total"排序时，部分费用**不计入** Total，但实际入住时强制收取，是差旅政策最易被坑的领域。

| 名称 | 中 | 何时强制收取 | 是否含在 OTA 显示 |
| --- | --- | --- | --- |
| Resort Fee | 度假村费 | 拉斯维加斯 / 夏威夷 / 加州度假村 | 通常**不**含在 Total |
| Destination Fee | 目的地费 | 纽约 / 迈阿密 / 部分纽约万豪希尔顿 | 通常不含 |
| City Tax | 城市税 | 欧洲多数城市 | 部分 OTA 含，部分不含 |
| Tourism Tax | 旅游税 | 西班牙 / 意大利 | 部分含 |
| Service Charge | 服务费 | 东南亚（一般 10%） | 通常含 |
| VAT | 增值税 | 欧洲 / 中国 / 日本 | 一般含 |
| Energy Surcharge | 能源附加费 | 欧洲冬季部分酒店 | 不一定含 |
| Parking | 停车 | 度假村 / 城市核心区 | 不含 |
| Wi-Fi | 网络 | 多数已免费 | 不含但通常 0 |
| Pet Fee | 宠物费 | 宠物友好酒店 | 不含 |

> 差旅系统在 `total_price` 之外应明确：
>
> - `room_subtotal`
> - `taxes_and_fees`
> - `mandatory_surcharges`（明确列项）
> - `optional_extras`
>
> 并在前端展示"**入住时还需支付**"。

## 8. 押金 / 担保

### 8.1 押金 (Deposit)

| 类型 | 收取节点 | 退还节点 | 备注 |
| --- | --- | --- | --- |
| 预付定金 | 预订时 | 不退或视政策 | 通常等于首晚房费 |
| 抵店押金 | 入住时 | 离店核账后 | 通常 = 1 晚房费 + RMB 500 杂费 |
| 杂费押金 | 入住时 | 离店核账后 | 仅杂费 |
| 信用卡担保 | 预订 / 入住 | 不实际扣款，仅冻结 | 国际酒店标配 |

### 8.2 担保 (Guarantee)

| 模式 | 含义 |
| --- | --- |
| Credit Card Guarantee (CCG) | 信用卡担保，不实际扣款 |
| Prepay / 全款预付 | 预订时即扣全额 |
| Deposit / 定金 | 仅扣首晚或 50% |
| Company Guarantee | 公司挂账担保（BTA / Direct Bill） |
| Voucher | 凭旅行社代金券 |

### 8.3 信用卡冻结金额（Pre-auth）

| 国家 / 类型 | 典型预授权金额 |
| --- | --- |
| 国内三星 | RMB 200–500（不含房费）/ 整段房费 |
| 国内五星 | RMB 1,000–2,000 / 段 |
| 美国 | USD 50–200 / 晚 |
| 欧洲 | EUR 50–100 / 晚 |
| 日本 | JPY 5,000–10,000 / 段 |

> 预授权一般 7–30 天自动释放，但部分银行最长 60 天，差旅政策建议提示员工预留额度。

## 9. 价格码与渠道关系（决策表）

| 价格码 | 主要渠道 | 是否对企业开放 | 备注 |
| --- | --- | --- | --- |
| BAR | 直销 / OTA / GDS | 是 | 默认 |
| CRP | TMC / 直连 / GDS | 仅协议公司 | 需公司 ID |
| GOV | GDS | 政府客 |  |
| AAA / AARP | 直销 / OTA | 凭卡 |  |
| MEMBER | 集团官网 / APP | 会员 | 需绑定账号 |
| PROMO | 全渠道 | 是 |  |
| WHOLESALE | 仅 B2B 批发商 | 不可直售 | OTA 限定 |
| OPAQUE | Hotwire / Priceline | 不可改 | 不显示品牌 |
| GROUP | 直销 / 销售 | 团体 | ≥10 间夜 |
| TOUR / FIT | 旅行社 | 散客打包 |  |

## 10. 价格保护 / Best Rate Guarantee

主要集团（Marriott / Hilton / IHG / Hyatt / Accor）均提供 BRG（Best Rate Guarantee）：

| 集团 | 政策 | 补偿 |
| --- | --- | --- |
| Marriott | "Best Rate Guarantee" | 首晚 25% off 或匹配价 + USD 50 / 晚 |
| Hilton | "Price Match Guarantee" | 匹配价 + 25% off |
| IHG | "Best Price Guarantee" | 匹配价 + 5x 积分（最低 USD 5） |
| Hyatt | "Best Rate Guarantee" | 匹配价 + 20% off |
| Accor | "Best Price Guarantee" | 匹配价 + 10% off |

**触发条件**：
- 通过集团官网 / APP 预订
- 同一天内发现 OTA / 第三方更低价
- 同房型、同日期、同政策、同币种
- 提交在入住前 24 小时
- 不含"会员限定"或"特殊群体"价

差旅系统价格审计逻辑应在工单层支持"提交 BRG 申请"。

## 11. 价格审计常见坑点

1. **OTA 现付价 vs 预付价**：现付价含税往往更高（因为 OTA 加价基数不同），且现付收押金；预付价虽便宜但取消政策更严
2. **会员价 / 协议价隐藏**：BAR 默认对所有人，会员价需登录、协议价需企业代码；同一房型同一时间可能有 4 个价格
3. **币种转换误差**：USD 200 在不同 OTA 显示为 RMB 1,440 / 1,452，差异源于 FX 时点 + DCC 加价
4. **税不含税混杂**：日本 / 韩国 / 美国本地预订常显示"不含税"，下单后金额跳变
5. **Resort Fee / Destination Fee 隐藏**：旅游城市必查 `mandatory_surcharges`
6. **促销价不可改**：早鸟立扣 + 不可退；员工误点后申诉率高
7. **会员升级与协议价不可叠加**：会员升级仅作用于 BAR，不作用于协议价 / 政府价
8. **延住价不一定 = BAR**：延住通常按"延住当日 BAR"，可能比首晚高很多

## 12. 价格码与差旅政策的关联（决策建议）

| 政策类型 | 推荐选用价格码 |
| --- | --- |
| 严格控成本 + 行程确定 | NRF / 早鸟 / 预付价 |
| 行程可能调整 | BAR / 免费取消 |
| VIP / 客户接待 | 协议价 + 含早 + Late C/O |
| 长期项目驻地 | 连住价 / 月租 / 长住公寓 |
| 团队 / 培训 | 团体价 + 主总挂账 |
| 临时差旅 | BAR + 24h 免费取消 |
| 国际差旅 | 直连 + 公司 BTA + 多币种 |

## 13. 与其他章节的关系

- 房型规范：[03_room_types_and_bedding.md](03_room_types_and_bedding.md)
- 渠道：[05_distribution_channels.md](05_distribution_channels.md)
- 退改 SOP：[07_modification_cancellation_sop.md](07_modification_cancellation_sop.md)
- 税务详情：[12_invoicing_tax_china.md](12_invoicing_tax_china.md)、[13_overseas_tax_and_fx.md](13_overseas_tax_and_fx.md)
- 报销合规：[14_reimbursement_compliance.md](14_reimbursement_compliance.md)
