# 02 术语表（中英对照）

#### 关键词
`术语 / 缩写 / OTA / GDS / CRS / PMS / RMS / RevPAR / ADR / OCC / LRA / NLRA / BAR / RACK / CTA / CTD / MLOS / EOH / BTA / CRD / FOC / NSF / HX`

> 字段格式：`英文 / 缩写` — 中文（说明 / 适用场景）

## 1. 房价与库存

- **Rack Rate** — 门市价 / 牌价（无折扣公开报价）
- **BAR (Best Available Rate)** — 最优可售价（动态浮动价，多数 OTA / 直连默认价格）
- **Floor Rate** — 价格底线（酒店允许的最低售价）
- **Promo / Promotional Rate** — 促销价
- **Corporate Rate / Negotiated Rate** — 企业协议价
- **LRA (Last Room Availability)** — 末房可售（合同保证：只要还有房就给协议价）
- **NLRA (Non-Last Room Availability) / Static Rate** — 非末房（库存紧张时酒店可关闭协议价）
- **Wholesale / Net Rate** — 净价（不含 OTA 加价）
- **Package Rate** — 套餐价（含早 / 含 SPA / 含交通）
- **Group Rate** — 团体价（≥10 间夜或定义为团体）
- **Day Use Rate** — 日租价（不过夜）
- **Crew Rate / Airline Rate** — 机组协议价
- **Government Rate** — 政府差旅价（GSA per diem 等）
- **Senior Rate** — 长者价
- **AAA Rate / AARP Rate** — 协会会员价
- **Opaque Rate** — 不透明价（Hotwire / Priceline 隐藏品牌）
- **Mobile Rate** — APP 限定价
- **Member Rate** — 会员价（最低保证 = MGR Member-Get-the-Rate）
- **MGR (Member-Get-the-Rate)** — 会员保证最优价
- **OBE / OBT (Online Booking Engine / Tool)** — 在线预订引擎
- **Inclusive Rate** — 含税价
- **Exclusive Rate / Net of Tax** — 不含税价
- **Total Stay Charge** — 整段住宿总额（多晚价格加总，含税费）

## 2. 库存与限制

- **CTA (Closed To Arrival)** — 关闭到达（当日不接受新入住，已入住可继续）
- **CTD (Closed To Departure)** — 关闭离开（不允许当日离店，等于强制延住）
- **MinLOS / MLOS (Minimum Length of Stay)** — 最低住宿晚数
- **MaxLOS** — 最高住宿晚数
- **Stop Sell** — 停售
- **Open Sell** — 开售
- **Allotment** — 配额（合同内固定预留）
- **Free Sale** — 自由销售（不占配额）
- **On Request** — 需求确认（不保证立即出单）

## 3. 状态码与房态

- **OCC (Occupied)** — 占用
- **VAC (Vacant)** — 空房
- **VC (Vacant Clean)** — 空净
- **VD (Vacant Dirty)** — 空脏
- **VR (Vacant Ready)** — 空净待售
- **OOO (Out of Order)** — 故障停用（短期）
- **OOS (Out of Service)** — 长期停用（如装修）
- **EA (Expected Arrival)** — 预到
- **ED (Expected Departure)** — 预走
- **DND (Do Not Disturb)** — 请勿打扰
- **DL / DD (Double Lock / Double Locked)** — 反锁
- **HSK / HK (Housekeeping)** — 客房部
- **EOH (End of House)** — 满房

## 4. 客人 / 入住相关

- **PAX** — 人数 (passengers)
- **ADL / CHL** — 成人 / 儿童
- **SGL / DBL / TWN / TPL / QUAD** — 单 / 双 / 双床 / 三人 / 四人
- **EB (Extra Bed)** — 加床
- **CR (Crib / Cot)** — 婴儿床
- **CI (Check-in) / CO (Check-out)** — 入住 / 离店
- **ETA (Estimated Time of Arrival) / ETD** — 预计抵 / 离时间
- **Walk-in** — 临柜散客
- **No-Show** — 未到客
- **Early Check-in / Late Check-out** — 提前入住 / 延迟离店
- **Day Use** — 钟点房（不过夜）
- **Stay Over** — 续住（在店内多住一晚）
- **Sleep Out** — 短期外出但保留房间
- **VIP / VVIP / Press** — 贵宾 / 超级贵宾 / 媒体
- **Repeat Guest** — 回头客
- **Walk** — 强制换酒店（超售场景）
- **Comp (Complimentary)** — 免费
- **House Use** — 内部使用（员工 / 检测 / 接待）

## 5. 房型 / 床型

- **Single (SGL)** — 单人房
- **Twin (TWN)** — 双床房
- **Double (DBL)** — 大床房
- **Queen** — 后双床（150–160 cm 宽）
- **King** — 国王床（180 cm+）
- **Hollywood Twin** — 双床合并（也称 Studio Twin）
- **Junior Suite** — 小套房
- **Suite** — 套房
- **Executive Suite** — 行政套房
- **Presidential Suite** — 总统套房
- **Connecting Room** — 连通房
- **Adjoining Room** — 相邻房（不连通）
- **Accessible Room / ADA Room** — 无障碍房
- **Smoking / Non-Smoking** — 吸烟 / 非吸烟
- **City View / Sea View / Mountain View / Garden View** — 城景 / 海景 / 山景 / 园景
- **Run of House (ROH)** — 不指定房型，由酒店分配
- **Family Room / Triple** — 家庭房 / 三人房
- **Studio** — 一居（开放式）
- **Loft** — 阁楼复式

## 6. 餐食

- **EP (European Plan)** — 不含餐
- **CP (Continental Plan)** — 含欧式早餐
- **BB (Bed & Breakfast)** — 含早餐
- **HB (Half Board / MAP)** — 含早 + 一正（午或晚）
- **FB (Full Board / AP)** — 含三餐
- **AI (All Inclusive)** — 全包（餐 + 酒水 + 部分活动）
- **DBB / DBLBB** — 双人含早

## 7. 渠道与分销

- **OTA (Online Travel Agency)** — 在线旅行社
- **TMC (Travel Management Company)** — 差旅管理公司
- **GDS (Global Distribution System)** — 全球分销系统（Sabre / Amadeus / Travelport / TravelSky）
- **CRS (Central Reservation System)** — 中央预订系统
- **PMS (Property Management System)** — 酒店管理系统
- **RMS (Revenue Management System)** — 收益管理系统
- **CM (Channel Manager)** — 渠道管理（如 SiteMinder / RateGain / DerbySoft / TravelClick）
- **DMC (Destination Management Company)** — 目的地服务商
- **NDC (New Distribution Capability)** — 新分销能力（航空为主）
- **API Direct Connect** — API 直连
- **Bedbank / Wholesaler** — 批发商
- **Metasearch** — 元搜索
- **Affiliate** — 联盟分销
- **MICE** — 会议、奖励、会展
- **Net Rate** — 净价（B2B）

## 8. 商务 / 合同

- **RFP (Request for Proposal)** — 询价邀请书
- **LOI (Letter of Intent)** — 意向书
- **MSA (Master Service Agreement)** — 主服务协议
- **NDA** — 保密协议
- **SLA (Service Level Agreement)** — 服务级别协议
- **KPI** — 关键绩效指标
- **TAC (Travel Advisory / Compliance)** — 差旅政策合规
- **OBT (Online Booking Tool)** — 在线预订工具（Concur Travel、Egencia、CWT、Amex GBT Neo）
- **GSA / Per Diem** — 美国联邦差旅日补
- **Sourcing** — 采购
- **Reverse Auction** — 逆向竞拍

## 9. 收益指标

- **Occupancy / OCC** — 出租率 = 已售房晚 / 可售房晚
- **ADR (Average Daily Rate)** — 平均房价 = 客房收入 / 已售房晚
- **RevPAR (Revenue per Available Room)** — 每间可售房收入 = 客房收入 / 可售房晚 = ADR × OCC
- **TRevPAR (Total RevPAR)** — 综合 RevPAR（含餐饮、宴会）
- **GOPPAR (Gross Operating Profit per Available Room)** — 营业毛利 RevPAR
- **MPI (Market Penetration Index)** — 市场占有指数
- **ARI (Average Rate Index)** — 平均房价指数
- **RGI (Revenue Generation Index)** — 营收生成指数
- **STR Report / STR Global** — 第三方酒店指标报告
- **Pace Report** — 预订进度报告

## 10. 财务 / 税务

- **VAT** — 增值税 (Value Added Tax)
- **GST** — 商品及服务税（澳新印新加坡等）
- **Service Charge** — 服务费
- **City / Tourism Tax** — 城市税 / 旅游税
- **Resort Fee** — 度假村费（强制收取，不含房价）
- **Destination Fee** — 目的地费（同 Resort Fee 性质）
- **Occupancy Tax** — 入住税（美国常见）
- **Government Tax** — 政府税（统称）
- **Tax Inclusive / Exclusive** — 含税 / 不含税
- **Net of Tax** — 不含税
- **Per Night / Per Stay / Per Person** — 计费单位
- **Folio** — 客账（账单合集）
- **Master Folio** — 总账（团队 / 公司挂账）
- **Incidentals** — 杂费（电话、洗衣、迷你吧）
- **Authorization Hold / Pre-auth** — 预授权
- **Final Charge / Settlement** — 终结
- **Chargeback** — 信用卡拒付
- **No-Show Fee** — 未到罚金
- **Cancellation Fee** — 取消费
- **Early Departure Fee** — 早离费
- **BTA (Business Travel Account) / Lodge Card** — 企业差旅账户卡
- **Virtual Card / VCC** — 虚拟卡
- **Direct Bill** — 月结挂账
- **CRD (Credit Card Required at Booking)** — 预订时需信用卡担保
- **CCG (Credit Card Guarantee)** — 信用卡担保
- **Deposit Required** — 需预付定金
- **Prepay / Post-pay** — 预付 / 现付
- **NSF (Non-Sufficient Funds)** — 资金不足
- **HX (Cancelled)** — 已取消（GDS 状态码）
- **HK (Confirmed)** — 已确认
- **UC (Unable to Confirm)** — 无法确认

## 11. 客诉 / 服务补救

- **Service Recovery** — 服务补救
- **Compensation Matrix / Comp Authority** — 补偿权限
- **Goodwill Adjustment** — 善意减免
- **Down-Grade / Up-Grade** — 降 / 升级
- **Walk** — 强制换店（超售）
- **Relocation** — 安置
- **Apology Letter / Service Manager** — 致歉信 / 服务经理
- **Recovery Tier** — 补救等级（轻 / 中 / 重）

## 12. 安全 / 合规

- **PIPL (Personal Information Protection Law)** — 个人信息保护法（中国 2021）
- **DSL / DSA (Data Security Law)** — 数据安全法（中国 2021）
- **CSL (Cybersecurity Law)** — 网络安全法（中国 2017）
- **GDPR** — 欧盟通用数据保护条例
- **CCPA / CPRA** — 加州消费者隐私法
- **PCI-DSS** — 支付卡行业数据安全标准
- **CIQ / Public Security Filing** — 公安境外人员临时住宿登记
- **AML / KYC** — 反洗钱 / 客户身份核实
- **DPIA (Data Protection Impact Assessment)** — 数据保护影响评估
- **SCC / BCR** — 标准合同条款 / 约束性公司规则（跨境数据）

## 13. 物流 / 入住安全

- **Front Desk / FD** — 前台
- **Concierge** — 礼宾
- **Bell Service** — 礼宾行李服务
- **Valet** — 代客泊车
- **Engineering** — 工程部
- **F&B (Food & Beverage)** — 餐饮
- **MEP** — 机电工程
- **AED** — 自动除颤仪
- **Sprinkler / Smoke Detector** — 喷淋 / 烟感
- **Fire Drill** — 消防演习
- **Evacuation Plan** — 疏散计划

## 14. 跨境与汇兑

- **FX (Foreign Exchange)** — 外汇
- **DCC (Dynamic Currency Conversion)** — 动态货币转换（POS 端结汇）
- **Multi-currency Settlement** — 多币种结算
- **MCC (Merchant Category Code)** — 商户类别码（酒店 7011、汽车旅馆 7012）

## 15. 缩写速查

| 缩写 | 全称 | 中文 |
| --- | --- | --- |
| ADR | Average Daily Rate | 平均房价 |
| BAR | Best Available Rate | 最优可售价 |
| BB | Bed & Breakfast | 含早 |
| CRS | Central Reservation System | 中央预订系统 |
| CTA | Closed to Arrival | 关闭到达 |
| CTD | Closed to Departure | 关闭离开 |
| EB | Extra Bed | 加床 |
| EP | European Plan | 不含餐 |
| HB | Half Board | 含早 + 一正餐 |
| LRA | Last Room Availability | 末房可售 |
| MICE | Meeting/Incentive/Conference/Exhibition | 会奖 |
| NLRA | Non-LRA | 非末房 |
| NDC | New Distribution Capability | 新分销能力 |
| NSF | Non-Sufficient Funds | 资金不足 |
| OBT | Online Booking Tool | 在线预订工具 |
| OCC | Occupancy | 出租率 |
| OOO | Out of Order | 故障停用 |
| OTA | Online Travel Agency | 在线旅行社 |
| PCI | Payment Card Industry | 支付卡行业 |
| PIPL | Personal Information Protection Law | 个保法 |
| RFP | Request for Proposal | 询价邀请书 |
| RMS | Revenue Management System | 收益管理系统 |
| ROH | Run of House | 不指定房型 |
| SLA | Service Level Agreement | 服务级别协议 |
| TMC | Travel Management Company | 差旅管理公司 |
| VCC | Virtual Credit Card | 虚拟卡 |
