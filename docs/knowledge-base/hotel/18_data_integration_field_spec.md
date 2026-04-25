# 18 数据接入与字段规范

#### 关键词
`数据 / 字段 / Schema / 主键 / 酒店 ID / 房型 ID / 价格码 / 状态码 / 库存 / 同步 / 接口 / API / OTA / GDS / 直连 / 直签`

## 1. 主数据 (Master Data)

### 1.1 酒店实体 (Hotel)

```yaml
hotel:
  hotel_id: string  # 内部主键 (UUID 或语义化"COUNTRY-CITY-NAME")
  external_ids:
    ctrip_id: string|null
    meituan_id: string|null
    fliggy_id: string|null
    booking_id: string|null
    expedia_id: string|null
    agoda_id: string|null
    marriott_marshacode: string|null  # 例 "BJSJW"
    hilton_chaincode_brand_code: string|null
    ihg_holidexcode: string|null
    hyatt_propertycode: string|null
    accor_rid: string|null
    huazhu_id: string|null
    jinjiang_id: string|null
    sabre_chain_pseudo_city: string|null
    amadeus_property_id: string|null
    googleplaces_id: string|null
    gaode_poi_id: string|null

  legal_name: string
  display_name_zh: string
  display_name_en: string
  brand: string
  chain: string
  category: enum[luxury, upper_upscale, upscale, upper_midscale, midscale, economy, extended_stay, resort, serviced_apt, vacation_rental]
  star_official: 1-5|null
  star_display: 1-5|null
  diamond_aaa: 1-5|null
  forbes_stars: int|null
  michelin_keys: 1-3|null

  geo:
    country_code_alpha2: "CN"
    country_code_alpha3: "CHN"
    region: string
    city: string
    city_id: string
    address_zh: string
    address_en: string
    postal_code: string
    latitude: float
    longitude: float
    timezone: "Asia/Shanghai"

  contact:
    phone_main: string
    phone_reservations: string
    fax: string
    email_general: string
    email_reservations: string
    email_billing: string
    website_url: string

  policies:
    checkin_time_local: "14:00"
    checkout_time_local: "12:00"
    early_checkin_fee: number|null
    late_checkout_fee_pct: number|null
    pet_friendly: bool
    smoking_allowed: bool
    age_restriction_min: 18
    foreigner_accepted: bool  # 中国大陆涉外资质
    pii_filing_required: bool  # 公安备案

  amenities:
    free_wifi: bool
    parking: enum[none, paid, free]
    breakfast_available: bool
    fitness: bool
    pool: bool
    spa: bool
    restaurant_count: int
    bar_count: int
    business_center: bool
    laundry: bool
    accessible_rooms_count: int

  audit:
    last_audited_at: timestamp
    audit_source: string
    data_freshness_days: int

  status: enum[active, suspended, closed, renovation]
```

### 1.2 房型 (RoomType)

参考 [03_room_types_and_bedding.md](03_room_types_and_bedding.md)。

### 1.3 价格码 (RatePlan)

```yaml
rate_plan:
  rate_plan_id: string
  hotel_id: string
  room_type_id: string
  external_rate_code: string

  rate_class: enum[BAR, RACK, CRP, GOV, AAA, MEMBER, MOBILE, PROMO, PKG, GROUP, OPAQUE, NRF, FRD]
  description_zh: string
  description_en: string

  pricing:
    base_currency: "CNY"
    rate_type: enum[per_night, per_stay, per_person]
    inclusive_of_taxes: bool
    inclusive_of_service_charge: bool
    breakfast: enum[none, single, double, triple, full_board]
    breakfast_age_free_under: int

  restrictions:
    min_los: int
    max_los: int
    advance_purchase_min_days: int
    advance_purchase_max_days: int
    cta: bool  # closed to arrival
    ctd: bool  # closed to departure
    valid_dow: [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
    blackout_dates: [date]
    member_only: bool
    company_code_required: bool

  cancel_policy:
    refundable: bool
    free_cancel_until_local: timestamp
    cancel_tiers:
      - until_offset_hours: 72
        fee_amount: 0
        fee_currency: "CNY"
        fee_pct_first_night: 0
      - until_offset_hours: 24
        fee_pct_first_night: 100
      - until_offset_hours: 0
        fee_amount_full_stay: true

  guarantee:
    method: enum[ccg, prepay, deposit, company_bill, none]
    deposit_amount: number|null
    deposit_currency: "CNY"

  audit:
    rate_loaded_at: timestamp
    source: enum[hotel_pms, ota, gds, wholesaler, channel_manager]
```

### 1.4 库存 (Inventory)

```yaml
inventory:
  hotel_id: string
  room_type_id: string
  date: date
  available_count: int
  open_to_arrival: bool
  open_to_departure: bool
  min_los: int
  max_los: int
  last_synced_at: timestamp
```

### 1.5 订单 (Reservation)

```yaml
reservation:
  reservation_id: string
  external_confirmation_no: string
  pms_reservation_id: string
  channel: enum[direct, ota, gds, wholesaler, tmc, obt]
  channel_partner: string

  tenant_id: string
  customer_id: string
  cost_center: string
  project_code: string

  hotel_id: string
  room_type_id: string
  rate_plan_id: string

  primary_traveler_id: string
  travelers: [traveler_id]
  pax_adults: int
  pax_children: int
  children_ages: [int]

  check_in_date: date
  check_out_date: date
  nights: int
  expected_arrival_local: timestamp|null
  expected_departure_local: timestamp|null

  pricing:
    base_currency: "CNY"
    nightly_rates: [number]
    room_subtotal: number
    taxes_total: number
    surcharges_total: number  # 强制项
    service_charge: number
    breakfast_charge: number
    incidentals: number
    total_inclusive: number

  cancel_policy_snapshot: object  # 见上 RatePlan.cancel_policy
  guarantee:
    method: enum[ccg, prepay, deposit, company_bill]
    payment_token: string  # masked
    payment_brand: string
    payment_last4: string

  status: enum[pending, confirmed, modified, cancelled, no_show, in_house, checked_out, refunded]

  events:
    - event_type: created
      occurred_at: timestamp
      actor: user_id|system
      payload: {}
    - event_type: confirmed
    - event_type: modified
    - event_type: cancelled

  request_id: string
  trace_id: string
  audit_chain: [hash]
```

## 2. 状态码与生命周期

### 2.1 GDS 标准状态码

| 状态码 | 全称 | 含义 |
| --- | --- | --- |
| HK | Holds Confirmed | 已确认 |
| HX | Holds Cancelled | 已取消 |
| HL | Holds Waitlist | 候补 |
| UC | Unable to Confirm | 无法确认 |
| US | Unable Sell | 无法售卖 |
| NO | No Action Taken | 无动作 |
| RR | Reconfirmed | 重新确认 |
| KK | OK | 标准确认 |
| TK | Telephone | 电话已确认 |
| DK | Direct | 直接确认 |
| UN | Unable | 无法 |
| WL | Waitlist | 候补 |

### 2.2 内部状态机

```
[pending] → confirmed → in_house → checked_out
       ↓         ↓
   cancelled  modified → confirmed (新版本)
       ↓
   refunded
```

### 2.3 防重复 / 幂等

- 出单需 `idempotency_key`
- 修改需基于 `version`（乐观锁）
- 取消需校验当前状态非 `cancelled`

## 3. 接口契约

### 3.1 标准接口（推荐）

```
POST   /v1/hotels/search           # 检索酒店
GET    /v1/hotels/{hotel_id}       # 详情
POST   /v1/rates/quote             # 询价
POST   /v1/reservations            # 出单
GET    /v1/reservations/{id}       # 详情
PATCH  /v1/reservations/{id}       # 改签
DELETE /v1/reservations/{id}       # 取消
POST   /v1/reservations/{id}/cancel # 取消（明确语义）
GET    /v1/reservations/{id}/folio  # 离店账单
POST   /v1/refunds                  # 退款
GET    /v1/inventory                # 库存
GET    /v1/rate-plans               # 价格码
```

### 3.2 错误码

| 码 | HTTP | 含义 |
| --- | --- | --- |
| `INPUT_INVALID` | 400 | 参数错 |
| `UNAUTHORIZED` | 401 | 未认证 |
| `FORBIDDEN` | 403 | 无权限 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `RATE_NOT_AVAILABLE` | 409 | 价格不存在 |
| `INVENTORY_OUT` | 409 | 无房 |
| `RESTRICTION_VIOLATION` | 409 | 受限 |
| `DUPLICATE_BOOKING` | 409 | 重复 |
| `GUARANTEE_DECLINED` | 402 | 担保失败 |
| `EXTERNAL_TIMEOUT` | 504 | 上游超时 |
| `EXTERNAL_ERROR` | 502 | 上游错 |
| `RATE_LIMITED` | 429 | 限流 |
| `INTERNAL_ERROR` | 500 | 内部错 |

### 3.3 幂等与超时

```
- 所有写接口必须支持 Idempotency-Key (请求头)
- 超时设置：搜索 5s / 询价 10s / 出单 30s / 取消 30s
- 超时后必须异步查询确认是否实际生效（fire-and-confirm）
```

## 4. 时间与时区

```
- 所有时间字段保留 UTC + 时区显式
- 酒店当地时间 = "Asia/Shanghai" 等 IANA TZ 名
- 入住 / 离店 = 日期 (YYYY-MM-DD)
- ETA / ETD = 带时区的 ISO 8601
- 取消截止时间 = 带时区的 ISO 8601
- 跨日订单：MinLOS 校验需考虑酒店时区
```

## 5. 货币与金额

```
- 所有金额必须分两个字段：amount + currency
- 金额建议存储为 minor units (分) 或 Decimal(18,4)
- 浮点数禁用
- 多币种订单需保留 base_currency + display_currency + fx_rate_at_booking
```

## 6. 隐私与脱敏

| 字段 | 处理 |
| --- | --- |
| 身份证号 / 护照号 | AES-256 加密存储，脱敏返回 `4421****1234` |
| 手机号 | 同上 |
| 邮箱 | 部分脱敏 `****@example.com` |
| 信用卡号 | PCI 合规 token，禁直存 |
| CVV | **永不存储** |
| 银行卡号 / 银行账号 | 加密存储 |
| 生日 / 国籍 | 加密 |
| 出行目的 / 项目 | 业务分级（机密 / 内部 / 公开） |

详见 [19_compliance_privacy_security.md](19_compliance_privacy_security.md)。

## 7. 数据同步

### 7.1 主从同步

```
Hotel CRS (master)
   ↓ Push (实时 WebSocket / Webhook)
Channel Manager
   ↓ Push
[OTA1, OTA2, OTA3, GDS, Wholesaler]
```

### 7.2 同步消息格式（OTA 标准）

```xml
<OTA_HotelRateAmountNotifRQ>
  <RateAmountMessages HotelCode="...">
    <RateAmountMessage>
      <StatusApplicationControl Start="2026-05-01" End="2026-05-31"
                                RatePlanCode="BAR" InvTypeCode="DLX"/>
      <Rates>
        <Rate>
          <BaseByGuestAmts>
            <BaseByGuestAmt AmountAfterTax="699" CurrencyCode="CNY"/>
          </BaseByGuestAmts>
        </Rate>
      </Rates>
    </RateAmountMessage>
  </RateAmountMessages>
</OTA_HotelRateAmountNotifRQ>
```

### 7.3 重试 / 死信队列

```
- 失败重试：指数退避 1s/2s/4s/8s/16s
- 最大重试次数：5 次
- 死信队列：超过 5 次进入 DLQ + 告警
- 幂等键：消息 hash + 时间窗
```

## 8. 数据质量监控

```
1. 完整性：必填字段 95%+
2. 一致性：内部 ID 与外部 ID 双向映射 100%
3. 时效性：库存同步延迟 ≤5 分钟
4. 准确性：抽样 100 条人工核对
5. 唯一性：去重率 ≥99.5%
6. 关联性：订单-酒店-房型-价格码可追溯 100%
```

## 9. 国际化字段

| 字段 | 多语言 |
| --- | --- |
| 酒店名 | zh-CN, zh-TW, en-US, ja, ko |
| 地址 | zh-CN, en-US |
| 描述 | zh-CN, en-US, ... |
| 设施名 | i18n 翻译 |
| 政策文本 | i18n 翻译（重要） |
| 取消政策描述 | 必须 |

## 10. 与其他章节的关系

- 房型规范：[03_room_types_and_bedding.md](03_room_types_and_bedding.md)
- 价格码：[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- 渠道：[05_distribution_channels.md](05_distribution_channels.md)
- 隐私 / 安全：[19_compliance_privacy_security.md](19_compliance_privacy_security.md)
- KPI：[20_sla_kpi_metrics.md](20_sla_kpi_metrics.md)
