# 01 行业概览与酒店分类

#### 关键词
`星级 / 国标 GB/T 14308 / AAA Diamond / Forbes Travel Guide / Michelin Key / 商务酒店 / 经济型 / 精选服务 / select service / 全服务 / full service / 度假 / 民宿 / 公寓 / 长租 / serviced apartment / 国际品牌 / 本土品牌 / 直营 / 加盟 / 委托管理 / OYO`

## 1. 国内星级评定（GB/T 14308 旅游饭店星级的划分与评定）

国内酒店星级由文化和旅游部组织评定，由低到高分为五级，每星级对应硬件、服务、配套要求。差旅场景重点掌握以下内容：

| 星级 | 标识 | 典型特征 | 差旅政策常见限制 |
| --- | --- | --- | --- |
| 一星 | 一颗银星 | 基本住宿、24h 前台 | 一般不在企业差旅可选范围 |
| 二星 | 两颗银星 | 加备品、电视、电话 | 部分一线员工 / 短途差旅可用 |
| 三星 | 三颗银星 | 24h 餐饮、商务中心 | 普通员工差标 |
| 四星 | 四颗金星 | 行政楼层、健身房 | 经理级 / 客户接待 |
| 五星 | 五颗金星 | 高端餐饮、礼宾 | 高管 / VIP 客户接待 |
| 白金五星 | 五颗金星 + Platinum | 顶级品牌、米其林餐厅 | 仅 C-level / 重要外宾 |

> **注意**：
> - 国标星级**强制三年复评一次**，可能被"摘星"。差旅系统应同步标注 `last_audited_at` 与 `current_status`（active / suspended / revoked）。
> - 部分酒店挂"五星标准"但**未参评**，差旅政策需明确"挂牌星级"与"实际评定星级"，二者**不等价**。
> - 海外酒店一般不使用中国国标星级，差旅系统通常使用 `display_star`（展示星级）与 `official_star`（官方星级）两个字段。

## 2. 国际评级体系

| 评级 | 国家 / 区域 | 评级方 | 等级范围 | 备注 |
| --- | --- | --- | --- | --- |
| AAA Diamond | 美国 / 加拿大 / 墨西哥 | AAA | 1–5 颗钻石 | 5 钻含 Inspector's Best of Housekeeping |
| Forbes Travel Guide | 全球 | Forbes | 推荐 / 4 星 / 5 星 | 注重服务流程与体验 |
| Michelin Key | 全球 | Michelin | 1 / 2 / 3 钥匙 | 2024 年起（米其林指南酒店篇） |
| Stars by Hotelstars Union | 欧盟 | HSU | 1–5 星 + Superior | 含 17 国统一标准 |
| LQA / FHR | 全球 | 第三方 | 内部审核 | 高奢酒店常用 |
| Tablet Hotels / 五星钻石奖 | 全球 | MO 集团等 | 编辑评级 | 设计 / 体验导向 |

## 3. 商业模式分类

### 3.1 按服务级别

| 类别 | 英文 | 典型品牌 | 适合差旅人群 |
| --- | --- | --- | --- |
| 奢华 | Luxury | The Ritz-Carlton、Four Seasons、Mandarin Oriental、Bulgari、Aman | 高管、外宾接待 |
| 高端 | Upper Upscale | Marriott、Sheraton、Hilton、Hyatt Regency、Conrad、Westin | 副总级 / 客户拜访 |
| 中高端 | Upscale | Crowne Plaza、Hilton Garden Inn、Courtyard、Renaissance、Doubletree、Pullman、桔子水晶 | 经理级 |
| 中端精选服务 | Upper Midscale Select Service | Holiday Inn Express、Hampton、Fairfield、Tru、Aloft、桔子、全季、亚朵 | 普通员工主力差标 |
| 经济 | Midscale / Economy | Holiday Inn、Days Inn、Super 8、汉庭、如家、7 天 | 一线员工 / 临时差旅 |
| 长住 | Extended Stay | Residence Inn、Homewood Suites、Staybridge、雅诗阁 | 长期出差 / 项目驻地 |
| 度假 | Resort | All-Inclusive、JW Resort、亚特兰蒂斯、太阳城 | 客户慰问 / 团建 |
| 公寓 / 民宿 | Serviced Apartment / Vacation Rental | 雅诗阁、馨乐庭、Airbnb、途家 | 中长期 / 多人差旅 |

### 3.2 按运营模式

| 模式 | 含义 | 风险 / 收益归属 | 差旅采购影响 |
| --- | --- | --- | --- |
| 直营 (Owned & Managed) | 业主自营 | 完全归业主 | 服务一致性高，价格谈判空间小 |
| 委托管理 (Managed) | 业主出资，品牌方派驻管理团队 | 品牌方收管理费、业主承担经营风险 | 服务标准受品牌约束，本地化决策慢 |
| 特许经营 (Franchise) | 业主独立经营，向品牌方支付加盟费、使用品牌系统 (PMS/CRS) | 业主自负盈亏 | 易出现"挂牌酒店但服务参差"问题 |
| 租赁 (Lease) | 品牌方承租物业再运营 | 品牌方完全负责 | 类似直营 |
| 软品牌 (Soft Brand Collection) | 保留独立标识 + 共享分销 | 业主主导 | 例：Marriott Autograph、Curio、Tribute、Voco |

### 3.3 按客源结构

- 商务型 (Commercial)：50% 以上散客 + 协议公司客
- 度假型 (Leisure / Resort)：60% 以上度假休闲客源
- 会议型 (Convention)：依赖 MICE 业务（Meeting / Incentive / Conference / Exhibition）
- 机场型 (Airport)：靠近机场，主打过境与延误客
- 长住型 (Extended Stay)：30 晚以上比例 ≥30%

## 4. 中国主要酒店集团

| 集团 | 代表品牌 | 房量量级（2025 末估） | 备注 |
| --- | --- | --- | --- |
| 锦江国际 (Jinjiang) | 锦江都城、维也纳、丽枫、希岸、白玉兰、麗枫、卢浮（海外） | ≈ 130 万间 | 中国最大酒店集团 |
| 华住 (H World) | 汉庭、全季、桔子、桔子水晶、宜必思、美居、施柏阁 | ≈ 100 万间 | 与 Accor 战略合作 |
| 首旅如家 (BTG Homeinns) | 如家、和颐、建国饭店、诺富特（合作） | ≈ 60 万间 | 央企背景 |
| 亚朵 (Atour) | 亚朵、亚朵 X、亚朵 S、A.T.HOUSE | ≈ 18 万间 | 已美股上市，主打"中端精选服务 + 零售" |
| 君亭 (Junting) | 君亭、君澜、夜泊、景澜 | ≈ 8 万间 | 中端度假 |
| 东呈 (Dossen) | 怡莱、宜尚、铂顿城市名人 | ≈ 6 万间 |  |
| 尚美数智 (Shangmei) | 尚客优、骏怡、兰欧 | ≈ 8 万间 | 下沉市场 |
| 都市 118 / OYO China | 经济型加盟 | ≈ 5 万间 | 模式风险较高 |

## 5. 国际主要酒店集团

| 集团 | 代表品牌（节选） | 总部 | 备注 |
| --- | --- | --- | --- |
| Marriott International | The Ritz-Carlton、St. Regis、JW Marriott、W、Westin、Sheraton、Marriott、Renaissance、Le Méridien、Courtyard、Fairfield、Aloft、Moxie、Autograph、Tribute Portfolio | 美国 | 全球房量第一，会员体系：Marriott Bonvoy |
| Hilton Worldwide | Waldorf Astoria、LXR、Conrad、Signia、Hilton、Curio、DoubleTree、Tapestry、Embassy Suites、Hilton Garden Inn、Hampton、Tru、Spark、Home2、Motto | 美国 | 会员体系：Hilton Honors |
| IHG Hotels & Resorts | Six Senses、Regent、InterContinental、Vignette、Hotel Indigo、Kimpton、voco、Crowne Plaza、Holiday Inn、Holiday Inn Express、Garner、Candlewood、Staybridge | 英国 | 会员体系：IHG One Rewards |
| Hyatt | Park Hyatt、Andaz、Grand Hyatt、Hyatt Regency、Hyatt、Hyatt Place、Hyatt House、Thompson、Alila、Miraval、Caption | 美国 | 会员体系：World of Hyatt |
| Accor | Raffles、Fairmont、Sofitel、SO/、Pullman、Mövenpick、Swissôtel、Novotel、Mercure、ibis、ibis Styles、ibis Budget、Mövenpick Living | 法国 | 会员体系：ALL — Accor Live Limitless |
| Wyndham | Wyndham Grand、Wyndham、Ramada、Days Inn、Super 8、TRYP、La Quinta | 美国 | 经济型为主 |
| Choice Hotels | Cambria、Ascend、Comfort、Sleep Inn、Quality Inn、Clarion、Econo Lodge | 美国 |  |
| Best Western | BW Premier Collection、BW Plus、BW、SureStay | 美国 |  |
| Radisson Hotel Group | Radisson Collection、Radisson Blu、Radisson、Park Inn | 美国 / 中国 (锦江控股) |  |
| Minor Hotels | Anantara、Avani、NH、NH Collection、Tivoli、Oaks | 泰国 |  |
| Mandarin Oriental | Mandarin Oriental | 香港 |  |
| Shangri-La | Shangri-La、Kerry、Jen、Hotel Jen、Traders | 香港 / 中国 |  |
| Four Seasons | Four Seasons | 加拿大 | 私有 |
| Aman Resorts | Aman、Janu | 瑞士 |  |
| Banyan Tree | Banyan Tree、Angsana、Cassia、Dhawa | 新加坡 |  |
| Belmond | Belmond | 英国 (LVMH) |  |
| Rosewood Hotels | Rosewood、New World、Pentahotels | 香港 (Chow Tai Fook) |  |

## 6. 酒店运营三大系统

### 6.1 PMS (Property Management System)

酒店内部"中枢"，处理：

- 入住 / 离店 / 房态
- 客账 / 押金 / 结账
- 客史 / 客人偏好
- 排房 / 清洁状态

主流：Opera Cloud (Oracle)、Stayntouch、Mews、Cloudbeds、Maestro、Apaleo、千里马 (Fidelio)、石基 (Shiji)、住哲、别样红、雅高 ResaWeb（自研）。

### 6.2 CRS (Central Reservation System)

集团级"中央订单池"：

- 接收所有渠道订单（直营官网、CRO、OTA、GDS）
- 统一房价、库存、会员等级
- 与 PMS 双向同步（housekeeping、回执）

主流：Oracle OPERA Cloud Distribution、Sabre SynXis、Pegasus、TravelClick iHotelier、Amadeus Anantapura、Marriott MARSHA、Hilton OnQ、IHG Holidex、Accor TARS、华住 HMS。

### 6.3 RMS (Revenue Management System)

实时定价 + 库存控制：

- 需求预测
- 动态房价 (Dynamic Pricing)
- 预订限制 (Length-of-Stay restriction、CTA / CTD / Min LOS)
- 团队报价决策

主流：IDeaS G3、Duetto、Atomize、HotelIQ、Cendyn Revintel、Smart Host、华住智慧定价。

## 7. 中国差旅市场结构

### 7.1 主要 TMC（Travel Management Company）

| TMC | 母公司 | 优势 | 备注 |
| --- | --- | --- | --- |
| 携程商旅 | 携程集团 | 国内库存最深、产品最全 | "携程商旅" + "Trip.Biz" |
| 美团商旅 / 美旅 | 美团 | 中端 / 经济型实力强 | 与本地生活协同 |
| 飞猪商旅 | 阿里 | 信用住、国际线 | 与支付宝信用绑定 |
| BCD Travel | 全球 TMC | 跨国企业 / 国际化场景 |  |
| CWT (Carlson Wagonlit) | 全球 TMC | 已被 Amex GBT 收购 |  |
| Amex GBT | 美运通 | 大型外企 | 全球差旅政策落地 |
| 同程商旅 | 同程 | 中小企业、灵活计费 |  |
| 凯撒差旅 / 春秋商旅 | 凯撒 / 春秋 | 国际差旅 + MICE |  |
| HRS | 德国 | 国际酒店采购、RFP |  |

### 7.2 OTA / 元搜索

| 角色 | 国内代表 | 海外代表 |
| --- | --- | --- |
| OTA（在线旅行社） | 携程、去哪儿、飞猪、美团、同程、艺龙 | Booking.com、Expedia、Hotels.com、Agoda、Hotwire、Vrbo、Airbnb |
| Metasearch（元搜索） | 飞常准、爱彼迎搜索、Trip 比价 | Google Hotels、Trivago、Kayak、Skyscanner、Tripadvisor |
| Wholesaler（批发商） | 众荟、皇包车 (B2B)、唐人接 | HotelBeds、WebBeds、GTA、TBO、Expedia TAAP、Booking B2B、HotelHub |
| GDS | TravelSky (中航信) | Sabre、Amadeus、Travelport (Galileo / Apollo / Worldspan) |

## 8. 关键趋势（2024–2026）

- **直连优先**：2025 年 Marriott / IHG 公开主推 Direct Connect API，差旅系统应优先接入直连 / GDS，再回退批发商。
- **NDC 渐进**：航空领域 NDC（New Distribution Capability）已成熟，酒店 NDC 仍以集团 API 为主。
- **企业 ESG 报告**：差旅平台需输出每次行程的 CO₂ 排放、可比基准（GSTC / HCMI 1.1）。
- **AI Agent 渗透**：自动改签、智能客服已成 TMC 标配。

## 9. 与本知识库其他章节的关系

- 渠道与分销详情：见 [05_distribution_channels.md](05_distribution_channels.md)
- 房型与房价规则：见 [03_room_types_and_bedding.md](03_room_types_and_bedding.md)、[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- 国内 vs 海外税务：见 [12_invoicing_tax_china.md](12_invoicing_tax_china.md) 与 [13_overseas_tax_and_fx.md](13_overseas_tax_and_fx.md)
