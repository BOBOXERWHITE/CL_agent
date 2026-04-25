# 05 渠道与分销

#### 关键词
`OTA / GDS / CRS / PMS / Channel Manager / 直连 / API / 批发商 / Bedbank / DerbySoft / SiteMinder / 携程 / 美团 / 飞猪 / Booking / Expedia / Agoda / HotelBeds / Sabre / Amadeus / Travelport / TravelSky / 中航信 / Marriott / Hilton / IHG / Hyatt / Accor`

## 1. 分销链路全景图

```
[酒店 PMS]  ⇄  [集团 CRS / 自营]  ⇄  [Channel Manager]  ⇄  [GDS / OTA / Wholesaler / Metasearch]
                                                  │
                                                  └→ TMC / OBT / 企业平台 / 散客
```

差旅运营要在 5 个层面理解一个订单的来源：

1. **库存源 (Inventory Source)**：酒店原始库存来自 PMS 还是集团 CRS
2. **价格源 (Rate Source)**：BAR / 协议价 / 净价
3. **分销路径 (Distribution Path)**：直连 / GDS / OTA / 批发
4. **结算路径 (Settlement Path)**：现付 / 预付 / 月结 / BTA / VCC
5. **服务路径 (Service Path)**：客诉、改签由谁负责（OTA、TMC、酒店）

## 2. 渠道分类

### 2.1 直销渠道 (Direct Channel)

| 子类 | 典型 | 特征 |
| --- | --- | --- |
| 集团官网 / APP | marriott.com / hilton.com / accor.com / 华住会 | 价格最优，会员积分 |
| 酒店官网 | 单体酒店官网 | 多用 SiteMinder / Cloudbeds 出库 |
| 集团 CRO (Central Reservation Office) | 800 / 400 电话预订 | 适合复杂行程 / 残障客 |
| 直签销售 (Sales Direct) | 销售经理 / Sales Director | 团队 / 高价值客户 |
| 微信 / 小程序 | 集团或 PMS 服务商 | 国内中端崛起渠道 |

### 2.2 OTA (Online Travel Agency)

| OTA | 国家 | 模式 | 库存来源 |
| --- | --- | --- | --- |
| 携程 / Trip.com | 中国 / 全球 | Merchant + Agency 混合 | 直连 / 自营批发 |
| 去哪儿 | 中国 | Merchant | 携程子公司 |
| 美团 | 中国 | Merchant 主 | 自营销售 + PMS 直连 |
| 飞猪 | 中国 | Agency 主 | 阿里电商生态 |
| 同程 | 中国 | Merchant + Agency | 与艺龙合并 |
| 艺龙 | 中国 | Merchant | 同程子公司 |
| 途家 | 中国 | Vacation Rental | 民宿 / 公寓 |
| Booking.com | 全球 (Booking Holdings) | Agency 为主 | 酒店直挂 |
| Agoda | 全球 (Booking Holdings) | Merchant + Agency | 亚太强势 |
| Expedia | 全球 (Expedia Group) | Merchant 主 | 自营 + Affiliate |
| Hotels.com | 全球 (Expedia) | Merchant | 与 Expedia 同库 |
| Vrbo | 全球 (Expedia) | Vacation Rental |  |
| Hotwire | 美国 (Expedia) | Opaque 模式 |  |
| Priceline | 美国 (Booking Holdings) | Express Deals (Opaque) + 标准 |  |
| Hostelworld | 全球 | 青年旅舍 |  |
| Despegar | 拉美 | OTA |  |
| MakeMyTrip | 印度 | OTA |  |
| Yatra | 印度 | OTA |  |
| Rakuten Travel | 日本 | OTA |  |
| Jalan | 日本 | OTA (Recruit) |  |

#### Merchant 模式 vs Agency 模式

| 维度 | Merchant | Agency |
| --- | --- | --- |
| 收款方 | OTA 收客户钱 | 酒店收客户钱 |
| 客户支付 | 在 OTA 平台支付 | 入住时酒店付 |
| 价格类型 | 净价（OTA 加价后销售） | BAR / 含佣价 |
| 佣金扣点 | OTA 已含 | 入住后酒店付 OTA 佣金 (10–22%) |
| 取消政策决定权 | OTA 主导 | 酒店主导 |
| 增值税开具方 | OTA 或酒店 | 酒店 |
| 适用 | 早鸟、不可退 | 灵活、含早 |
| 国内典型 | 携程预付、美团 | 携程现付、Booking |

### 2.3 GDS (Global Distribution System)

| GDS | 母公司 | 主要市场 | 备注 |
| --- | --- | --- | --- |
| Sabre | 美国 | 全球，北美强 | 与 SynXis CRS 整合 |
| Amadeus | 西班牙 | 欧洲、亚太 | 与 Anantapura / TravelClick 配套 |
| Travelport | 美国 | 含 Galileo / Apollo / Worldspan | 主要英伦市场 |
| TravelSky / 中航信 | 中国 | 国内航旅 / 政企 | 与航司体系深度整合 |
| Pegasus | 美国 | 中小酒店 | 独立 GDS Aggregator |

差旅 / TMC 通过 GDS 接入酒店时：

- 价格码以 4 字符 RateAccessCode 形式传递
- 入住凭 GDS PNR + Confirmation Number
- 结算多为月结挂账
- 数据规范：HEDNA Plus、OTA 标准

### 2.4 批发商 / Bedbank

| 批发商 | 总部 | 业务量级 | 特点 |
| --- | --- | --- | --- |
| HotelBeds | 西班牙 | 全球最大 | 多源聚合 |
| WebBeds | 澳洲 | 全球 | 与 Hotelbeds 竞争 |
| TBO Holidays | 印度 / 阿联酋 | 全球 | 强势在中东 / 南亚 |
| GTA Travel (Kuoni) | 全球 | 已与 Hotelbeds 合并 |  |
| Miki Travel | 日本 | 亚太 |  |
| 众荟 | 中国 | 国内 | 携程系统 |
| 唐人接 | 中国 | 北美华人差旅 |  |
| Expedia TAAP / Affiliate | 全球 | 旅行社接入 Expedia 库存 |  |
| Booking.basic / Booking B2B | 全球 | OTA → B2B 转售 |  |

差旅系统接入批发商需关注：

- 净价 + 自定义 markup
- 取消政策严格（多数 NRF）
- 多供应商同酒店重复（去重逻辑必备）
- 多币种结算

### 2.5 元搜索 (Metasearch)

| 元搜索 | 区域 | 模式 |
| --- | --- | --- |
| Google Hotels | 全球 | CPC / CPA |
| Trivago | 全球 | CPC |
| Tripadvisor | 全球 | CPC + Plus 订阅 |
| Kayak | 全球 (Booking) | CPC |
| Skyscanner | 全球 (Trip.com) | CPC |
| Trip.com 比价 | 全球 | 元搜索 |
| HotelsCombined | 全球 (Booking Holdings) | CPC |

元搜索本身**不出单**，差旅平台仅在用户研究阶段触达。

### 2.6 Channel Manager (渠道管理器)

| Channel Manager | 总部 | 强项市场 |
| --- | --- | --- |
| SiteMinder | 澳洲 | 全球 SMB |
| RateGain | 印度 | 中高端 |
| DerbySoft | 美国 | 大集团直连 (Marriott/Hilton/IHG/Hyatt) |
| TravelClick (Amadeus) | 美国 | 中型集团 |
| Pegasus | 美国 | 独立酒店 |
| RateTiger | 印度 | SMB |
| 千里马 / Shiji ReviewPRO | 中国 | 国内中高端 |
| WuBook | 意大利 | 欧洲 SMB |

## 3. 差旅典型分销选型

### 3.1 国内差旅

| 公司规模 | 推荐主路径 | 备用路径 |
| --- | --- | --- |
| 大型企业（年差旅额 > RMB 5000 万） | TMC + 协议价（携程商旅 / 美团商旅）+ 部分集团直连（华住 / 锦江） | OBT 内嵌 BAR + 单笔垫付 |
| 中型企业 | 携程商旅 / 美团商旅，全员 OBT | 微信 / 小程序临时报销 |
| 小型企业 | 个人 OTA + 报销 | 散客直签 1–2 家协议酒店 |

### 3.2 国际差旅

| 公司规模 | 推荐主路径 | 备用路径 |
| --- | --- | --- |
| 跨国 / 外企 | Concur Travel / Egencia / Amex GBT Neo + GDS + 集团直连 + BTA | OTA 应急 |
| 国内出海 | TMC（携程商旅 / BCD / Amex GBT）+ Hotelbeds 批发 | OTA 散客 |
| 中小 | 携程商旅国际 + Booking 公司账户 |  |

## 4. 关键集成接口与协议

| 协议 / 标准 | 适用 | 说明 |
| --- | --- | --- |
| OTA Specification (OpenTravel Alliance) | 通用 | XML 标准 |
| HEDNA Plus | 中端聚合 |  |
| HotelXML | 早期 | 已被 OTA 取代 |
| HTNG (Hotel Technology Next Gen) | 现代 | 新一代规范 |
| OTA Hotel Rate Amount Notif (OTA_HotelRateAmountNotifRQ) | 价格推送 | OTA 经典 |
| OTA Hotel Inv Count Notif | 库存推送 |  |
| OTA Hotel Avail | 可售查询 |  |
| OTA Hotel Res | 预订 |  |
| OTA Hotel Res Modify / Cancel | 改 / 退 |  |
| OTA Read | 读取订单 |  |
| OTA Notify | 通知 |  |
| Marriott / Hilton 内部 API | 大集团直连 | 替代 GDS |
| GDS Apollo / Worldspan / Galileo Native | Travelport |  |
| Amadeus Hotel API | Amadeus | RESTful |
| Sabre Hotel Content API | Sabre | RESTful |
| Trip.com Open Platform / 携程开放平台 | OTA 合作伙伴 | 国内主流 |

## 5. 价格 / 库存同步常见模式

| 模式 | 含义 | 同步频率 |
| --- | --- | --- |
| Push 模式 | 酒店主动推送给 Channel Manager | 实时 |
| Pull 模式 | OTA 定时拉取 | 5–15 分钟 |
| 主从同步 | 集团 CRS 主，OTA 从 | 实时 |
| 互不为主 | 各 OTA 独立配置 | 易超售 |

> **超售（Overbooking）原因**通常是 Push 失败或 Pull 滞后，差旅平台需在订单层增加"出单时刻 vs 库存最近同步时刻 ≤ N 分钟"的告警阈值。

## 6. 渠道差异决策表

| 维度 | 直连 / 集团官网 | OTA | GDS / TMC | 批发商 |
| --- | --- | --- | --- | --- |
| 价格 | 一般 + 会员价 | BAR + 偶有促销 | 协议价 / BAR | 净价 |
| 库存深度 | 高 | 中 | 中 | 中（可能延迟） |
| 取消政策灵活性 | 高 | 中 | 中 | 低 |
| 改签支持 | 高 | 中（OTA 客服） | 高（TMC） | 低 |
| 客诉处理 | 直接酒店 | OTA + 酒店 | TMC + 酒店 | 通过批发商 |
| 发票 | 酒店 | OTA / 酒店 | TMC / 酒店 | 批发商 |
| 月结 | 集团 BTA | 较少 | 标准 | 标准 |
| 国际差旅 | 集团强 | 通用 | 标准 | 适合非主流市场 |
| 适合场景 | 高端 / 会员 | 散客 | 企业差旅 | 长尾酒店 / 度假 |

## 7. 渠道反向限制（Rate Parity）

集团 / 酒店与 OTA 之间存在 **价格平价 (Rate Parity)** 条款，常见类型：

| 类型 | 含义 |
| --- | --- |
| Wide Parity | 全球所有渠道同价 |
| Narrow Parity | 仅约束公开渠道（不含会员 / 不含未公开促销） |
| No Parity | 完全自由（欧盟 2015+ 多数解除） |

差旅平台在与酒店谈判时如要"低于 OTA 价"，需绕过：

- 会员限定（封闭群体）
- 协议价 + 公司代码（封闭群体）
- 套餐捆绑（不同 SKU）
- 闪购 / 移动端 / 限时（动态偏离）
- 团队 / 长住

## 8. 国内差旅特有渠道场景

### 8.1 信用住 / 免押预订

- 飞猪 / 携程 / 美团均有"芝麻信用 / 微信支付分"免押模式
- 订单不收押金、不预授权，离店后聚合扣款
- 差旅政策应明确：免押模式下若员工破坏 / 杂费纠纷，由谁兜底

### 8.2 钟点房 / 日租

- 携程、美团、艺龙均提供 4 / 6 / 8 小时钟点房
- 报销政策一般**不允许**钟点房（疑似非差旅）

### 8.3 公寓 / 民宿

- 途家、爱彼迎中国（已退出）、木鸟、美团民宿
- 多数无发票或仅"住宿费 + 服务费"普票
- 差旅政策应规定**仅限审批后的临时项目使用**

### 8.4 长住租赁

- 雅诗阁、馨乐庭、华住智选 (Crystal Orange Long-stay)
- 30 晚 + 月租，签长租合同走房屋租赁，发票内容可能为"租赁服务"，影响进项税

## 9. 国际差旅特有场景

### 9.1 GDS 私网价

- Amex GBT、BCD、CWT、HRS、CWT 等通过 GDS 加载企业自有协议价
- TMC 通过 `corporate_id` (CRC) 或公司 `IATA` 号识别
- 差旅政策应在每个酒店维度记录 `crc_code` 与 `iata` 同步状态

### 9.2 OBT (Online Booking Tool)

| OBT | 母公司 | 强项 |
| --- | --- | --- |
| Concur Travel | SAP | 全球外企 |
| Egencia | American Express GBT | 北美 / 欧洲 |
| Amex GBT Neo / Neo1 | American Express GBT | 全球 |
| Cytric | Amadeus | 欧洲 |
| KDS | Traveldoo | 欧洲 |
| Cliqbook | Concur 老版 |  |
| Deem Travel | 美国 |  |
| TravelPerk | 西班牙 |  |
| Spotnana | 美国 | 新一代 NDC |

### 9.3 跨境 Lodge Card / BTA

- AmEx BTA / Lodge Card / VCC
- Visa Commercial Card
- Diners Club Corporate
- 国内招商银行差旅卡 / 中信信银易付

### 9.4 NDC 与 New Distribution

虽然 NDC 主要用于航空，部分集团（IHG、Marriott）已开始把 NDC-like 模式套用到酒店：

- 新内容（套餐、动态包装、定制化）
- 直连优先于 GDS
- 个性化定价

## 10. 渠道选择决策表

| 用例 | 推荐渠道 |
| --- | --- |
| 高管出行，需 5 星 + 行政待遇 | 集团直连 + 协议价 + 会员升级 |
| 一线员工短差，控成本 | OBT + BAR + 早鸟 |
| 国际客户来访接待 | GDS / TMC + 协议价 + Late C/O |
| 多人长期项目 | 长住公寓 + 月结 |
| 临时改签场景多 | 直连 + 灵活取消 BAR |
| 海外冷门城市 | 批发商 (Hotelbeds) + OBT |
| 政府 / 国企严格预算 | TravelSky + 国内中央 OTA |
| 客户慰问 / MICE | Sales 直签 + 团队价 |

## 11. 渠道事件常见异常

| 异常 | 现象 | 排查方向 |
| --- | --- | --- |
| 价格不一致 | 同房型同日期，OTA / 直连差 5%+ | Rate Parity 漂移 / 会员限价泄露 |
| 库存不一致 | OTA 显示有房，酒店端无房 | Channel Manager 同步失败 |
| 双订单 | 同一住客两笔订单 | 多渠道误下单 / API 重试 |
| 出单失败 | 系统提示"已订房", PMS 无记录 | 直连消息丢失 / 异步未到 |
| 预订成功后被砍单 | 酒店退订 | 超售 / 价格错误 / 库存关闭 |
| 价格币种异常 | 显示 USD 实扣 RMB | DCC 加价 |
| 免费取消窗口被取消 | 协议显示 24h 免费但实际收费 | 价格码混合（套餐价、移动价） |

## 12. 与其他章节的关系

- 价格码：[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- 预订流程：[06_booking_sop.md](06_booking_sop.md)
- 数据字段：[18_data_integration_field_spec.md](18_data_integration_field_spec.md)
- 改签 / 退订：[07_modification_cancellation_sop.md](07_modification_cancellation_sop.md)
